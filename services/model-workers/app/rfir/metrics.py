"""Prometheus-style metrics for the RFIR worker (§5.4, optional).

Tracks cumulative counters across jobs processed by this worker process:
  - rfir_gpu_seconds_total{op="..."}   — cumulative GPU time per op
  - rfir_tier_count{tier="A|B|C|D"}    — number of shots run per tier
  - rfir_jobs_total                    — number of jobs completed
  - rfir_downgrades_total              — number of budget downgrades applied
  - rfir_cost_usd_total                — cumulative estimated cost
  - rfir_model_disk_bytes              — weights currently on disk (gauge)
  - rfir_model_fetch_bytes_total       — bytes fetched because a role was cold
  - rfir_model_hit_roles_total         — role requests already resident
  - rfir_model_miss_roles_total        — role requests that needed a download

No external dependency (no `prometheus_client`) — emits the standard text
exposition format directly, which is all `/metrics` scraping requires.

Spec reference: rfir-inference-engine-implementation.md §5.4
"""
from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.rfir.executor.context import ExecutionContext

logger = logging.getLogger(__name__)


class MetricsRegistry:
    """In-process counters for RFIR worker observability."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.gpu_seconds_by_op: dict[str, float] = defaultdict(float)
        self.tier_count: dict[str, int] = defaultdict(int)
        self.jobs_total: int = 0
        self.downgrades_total: int = 0
        self.cost_usd_total: float = 0.0
        # Disk working set (docs/superpowers/specs/2026-08-21-rfir-role-residency-design.md)
        self.model_disk_bytes: int = 0  # gauge: last observation, not a sum
        self.model_fetch_bytes_total: int = 0
        self.model_hit_roles_total: int = 0
        self.model_miss_roles_total: int = 0

    def record_job(self, ctx: "ExecutionContext") -> None:
        """Fold a completed job's ExecutionContext into the running totals."""
        with self._lock:
            self.jobs_total += 1
            for node in ctx.node_metrics:
                self.gpu_seconds_by_op[node.op] += node.gpu_ms / 1000.0
            for tier, count in ctx.tier_distribution.items():
                self.tier_count[tier] += count
            self.downgrades_total += len(ctx.downgrades)
            self.cost_usd_total += ctx.cost_estimate_usd()

    def record_residency(
        self,
        *,
        hot_roles: frozenset[str],
        missing_roles: frozenset[str],
        hot_bytes: int,
        miss_bytes: int,
        disk_bytes: int,
    ) -> None:
        """Fold one job's disk working set into the counters.

        Also emits a single JSON line per job so ρ̂ can be tracked over time
        without a Prometheus scrape — that ratio is the claim this design
        makes, and it should be checkable from a log tail.
        """
        from app.rfir.models.residency import catalog_bytes_fp16

        with self._lock:
            self.model_hit_roles_total += len(hot_roles)
            self.model_miss_roles_total += len(missing_roles)
            self.model_fetch_bytes_total += miss_bytes
            self.model_disk_bytes = disk_bytes

        catalog = catalog_bytes_fp16(False)
        logger.info(
            json.dumps(
                {
                    "roles": sorted(hot_roles | missing_roles),
                    "hot_bytes": hot_bytes,
                    "miss_bytes": miss_bytes,
                    "disk_bytes": disk_bytes,
                    "rho_hat": hot_bytes / catalog if catalog else 0.0,
                },
                sort_keys=True,
            )
        )

    def render_prometheus(self) -> str:
        """Render all counters in Prometheus text exposition format."""
        with self._lock:
            lines: list[str] = []

            lines.append("# HELP rfir_gpu_seconds_total Cumulative GPU seconds spent per op.")
            lines.append("# TYPE rfir_gpu_seconds_total counter")
            for op, seconds in sorted(self.gpu_seconds_by_op.items()):
                lines.append(f'rfir_gpu_seconds_total{{op="{op}"}} {seconds:.4f}')

            lines.append("# HELP rfir_tier_count Number of shots executed per tier.")
            lines.append("# TYPE rfir_tier_count counter")
            for tier, count in sorted(self.tier_count.items()):
                lines.append(f'rfir_tier_count{{tier="{tier}"}} {count}')

            lines.append("# HELP rfir_jobs_total Number of RFIR jobs completed.")
            lines.append("# TYPE rfir_jobs_total counter")
            lines.append(f"rfir_jobs_total {self.jobs_total}")

            lines.append("# HELP rfir_downgrades_total Number of budget downgrades applied.")
            lines.append("# TYPE rfir_downgrades_total counter")
            lines.append(f"rfir_downgrades_total {self.downgrades_total}")

            lines.append("# HELP rfir_cost_usd_total Cumulative estimated cost in USD.")
            lines.append("# TYPE rfir_cost_usd_total counter")
            lines.append(f"rfir_cost_usd_total {self.cost_usd_total:.6f}")

            lines.append("# HELP rfir_model_disk_bytes Model weights currently resident on disk.")
            lines.append("# TYPE rfir_model_disk_bytes gauge")
            lines.append(f"rfir_model_disk_bytes {self.model_disk_bytes}")

            lines.append(
                "# HELP rfir_model_fetch_bytes_total Bytes fetched because a role was not resident."
            )
            lines.append("# TYPE rfir_model_fetch_bytes_total counter")
            lines.append(f"rfir_model_fetch_bytes_total {self.model_fetch_bytes_total}")

            lines.append("# HELP rfir_model_hit_roles_total Role requests already on disk.")
            lines.append("# TYPE rfir_model_hit_roles_total counter")
            lines.append(f"rfir_model_hit_roles_total {self.model_hit_roles_total}")

            lines.append("# HELP rfir_model_miss_roles_total Role requests that needed a fetch.")
            lines.append("# TYPE rfir_model_miss_roles_total counter")
            lines.append(f"rfir_model_miss_roles_total {self.model_miss_roles_total}")

            return "\n".join(lines) + "\n"


# Process-wide singleton — the worker has one registry per process.
registry = MetricsRegistry()


class _MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (stdlib method name)
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        body = registry.render_prometheus().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # silence default stderr logging for every scrape


def serve_metrics(port: int = 9108) -> HTTPServer:
    """Start a background HTTP server exposing /metrics. Returns the server
    (caller is responsible for calling .shutdown() to stop it).
    """
    server = HTTPServer(("0.0.0.0", port), _MetricsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
