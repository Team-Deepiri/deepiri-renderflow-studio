"""Layer 2 client — asks the orchestrator to vet a ShotList before compile.

Spec reference: guardrails-implementation.md §6. The gate itself lives in
`services/orchestrator/app/guardrails/plan_guard.py` because it needs the
project's policy row and writes to `guardrail_decisions`; this process only
has the queue. So the shot list goes over HTTP and comes back either
approved (with any tier downgrades applied) or blocked.

Env: RENDERFLOW_ORCHESTRATOR_URL (default http://127.0.0.1:8080)
     RENDERFLOW_PLAN_GUARD_TIMEOUT (seconds, default 10)
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_PATH = "/internal/guardrails/plan"


class PlanBlocked(Exception):
    """Raised when the plan gate rejects the shot list, or cannot be reached."""


def _base_url() -> str:
    return os.environ.get("RENDERFLOW_ORCHESTRATOR_URL", "http://127.0.0.1:8080").rstrip("/")


def _timeout() -> float:
    return float(os.environ.get("RENDERFLOW_PLAN_GUARD_TIMEOUT", "10"))


def _post(url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def check_plan(job_id: str, shot_list) -> list[dict[str, Any]]:
    """Run the Layer 2 gate on `shot_list`.

    Returns the gate's shot entries so tier downgrades can be applied back
    onto the caller's ShotList. Raises PlanBlocked on a block verdict or on
    any failure to obtain one.
    """
    body = {
        "job_id": job_id,
        "shots": [
            {
                "description": s.description,
                "duration_sec": s.duration_sec,
                "tier": s.tier.value,
            }
            for s in shot_list.shots
        ],
    }

    try:
        resp = _post(f"{_base_url()}{_PATH}", body, _timeout())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise PlanBlocked(f"plan gate returned HTTP {e.code} (fail-closed): {detail}") from e
    except Exception as e:
        raise PlanBlocked(f"plan gate unreachable (fail-closed): {e}") from e

    verdict = resp.get("verdict")
    if verdict == "block":
        raise PlanBlocked(f"{resp.get('reason_code') or 'PLAN_UNSAFE'}: {resp.get('details')}")
    if verdict != "allow":
        # escalate/redact are not blocks (§3) — proceed, but leave a trail.
        logger.info("job %s: plan gate returned verdict=%r", job_id, verdict)

    return (resp.get("details") or {}).get("shots", [])
