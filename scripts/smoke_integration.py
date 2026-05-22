#!/usr/bin/env python3
"""Start orchestrator on ephemeral ports, hit HTTP + gRPC, exit 0 on success."""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCH = ROOT / "services" / "orchestrator"
GEN = ORCH / "app" / "gen"


def _orchestrator_python() -> Path:
    """Python from the orchestrator Poetry env (Git gpu-utils + lib/renderflow_queue)."""
    in_project = ORCH / ".venv" / "bin" / "python"
    if in_project.is_file():
        return in_project
    try:
        root = subprocess.check_output(
            ["poetry", "env", "info", "-p"],
            cwd=str(ORCH),
            text=True,
            timeout=30,
        ).strip()
        cand = Path(root) / "bin" / "python"
        if cand.is_file():
            return cand
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return Path(sys.executable)


def _sse_collector(port: int, collected: list, stop: threading.Event) -> None:
    """Read /v1/events in a background thread and collect data lines."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/events", timeout=35) as r:
            while not stop.is_set():
                line = r.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text.startswith("data:"):
                    collected.append(text[5:].strip())
    except Exception:
        pass


def main() -> int:
    http_port = int(os.environ.get("SMOKE_HTTP_PORT", "18081"))
    os.environ["RENDERFLOW_HTTP_PORT"] = str(http_port)
    os.environ["RENDERFLOW_GRPC_PORT"] = str(http_port + 1)
    os.environ["RENDERFLOW_AI_STAGE_MS"] = "1"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ORCH)])
    py = _orchestrator_python()
    proc = subprocess.Popen(
        [str(py), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(http_port)],
        cwd=str(ORCH),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{http_port}/health", timeout=0.5) as r:
                    if r.status == 200:
                        break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.2)
        else:
            print("timeout waiting for /health", file=sys.stderr)
            return 1

        with urllib.request.urlopen(
            f"http://127.0.0.1:{http_port}/v1/capabilities", timeout=2
        ) as r:
            cap = json.loads(r.read().decode())
        if "gpu" not in cap or "service" not in cap:
            print("capabilities response missing keys:", cap, file=sys.stderr)
            return 1

        proj_req = urllib.request.Request(
            f"http://127.0.0.1:{http_port}/v1/projects",
            data=json.dumps({"name": "smoke-project"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(proj_req, timeout=5) as r:
            proj = json.loads(r.read().decode())
        pid = proj["id"]

        sse_events: list[str] = []
        sse_stop = threading.Event()
        sse_thread = threading.Thread(
            target=_sse_collector, args=(http_port, sse_events, sse_stop), daemon=True
        )
        sse_thread.start()
        time.sleep(0.1)

        req = json.dumps(
            {"project_id": pid, "mode": "scene", "prompt": "smoke", "metadata": {}}
        ).encode()
        http_req = urllib.request.Request(
            f"http://127.0.0.1:{http_port}/v1/jobs",
            data=req,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(http_req, timeout=5) as r:
            body = json.loads(r.read().decode())
        job_id = body["id"]

        for _ in range(50):
            with urllib.request.urlopen(
                f"http://127.0.0.1:{http_port}/v1/jobs/{job_id}", timeout=2
            ) as r:
                st = json.loads(r.read().decode())
            if st.get("status") == "committed":
                break
            time.sleep(0.15)
        else:
            print("job did not reach committed:", st, file=sys.stderr)
            return 1

        time.sleep(0.3)
        sse_stop.set()
        sse_thread.join(timeout=2)

        statuses: set[str] = set()
        for raw in sse_events:
            if job_id in raw:
                try:
                    statuses.add(ast.literal_eval(raw).get("status", ""))
                except Exception:
                    pass
        if "preparing" not in statuses or "committed" not in statuses:
            print(f"SSE events missing expected statuses, got: {statuses}", file=sys.stderr)
            return 1

        sys.path.insert(0, str(GEN))
        import grpc  # noqa: E402
        import renderflow_pb2  # noqa: E402
        import renderflow_pb2_grpc  # noqa: E402

        ch = grpc.insecure_channel(f"127.0.0.1:{http_port + 1}")
        ai = renderflow_pb2_grpc.AiSessionServiceStub(ch)
        h = ai.Health(renderflow_pb2.HealthRequest())
        if h.status != "ok":
            print("grpc health bad", h, file=sys.stderr)
            return 1
        pr = renderflow_pb2_grpc.ProjectServiceStub(ch)
        created = pr.CreateProject(
            renderflow_pb2.CreateProjectRequest(name="grpc-proj", owner_id="", fps_num=24, fps_den=1, sample_rate=48000)
        )
        if not created.id:
            print("grpc CreateProject failed", file=sys.stderr)
            return 1
        ch.close()
        print("smoke ok: http + job pipeline + SSE events + grpc AI + grpc Project")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        err = proc.stderr.read() if proc.stderr else ""
        if proc.returncode not in (0, -15, -9) and err:
            print(err, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
