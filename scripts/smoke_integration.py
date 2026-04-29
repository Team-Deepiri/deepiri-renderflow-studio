#!/usr/bin/env python3
"""Start orchestrator on ephemeral ports, hit HTTP + gRPC, exit 0 on success."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCH = ROOT / "services" / "ai-orchestrator-fastapi"
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
        print("smoke ok: http + job pipeline + grpc AI + grpc Project")
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
