"""Opt-in Docker evidence on disposable projects; never uses host port 3000."""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from agent.validator import check_application_url
from tests.fixture_support import materialize

ROOT = Path(__file__).resolve().parents[1]


def run(command, cwd, timeout=30, extra_env=None):
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                                timeout=timeout, env=dict(os.environ, NO_COLOR="1", TERM="dumb", COLUMNS="240", **(extra_env or {})))
        return {"command": command, "returncode": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr}
    except subprocess.TimeoutExpired:
        return {"command": command, "returncode": None, "stdout": "", "stderr": f"Timed out after {timeout}s"}


def cli(command, repo):
    return run([sys.executable, "-m", "agent.main", command, str(repo)], ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prefix = "devops-baseline-" + uuid.uuid4().hex[:10]
    image = prefix + ":local"
    report = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "agent_commit": run(["git", "rev-parse", "HEAD"], ROOT)["stdout"].strip(),
        "platform": platform.platform(),
        "scope": "Controlled Docker fixture evidence, NOT full validate --run acceptance: ephemeral host port and a fixture-owned Compose file bypass production port-3000 assumptions.",
        "observations": {}, "cleanup": [], "errors": [],
    }
    projects = []
    image_built = False
    with tempfile.TemporaryDirectory(prefix=prefix + "-") as directory:
        root = Path(directory)
        try:
            # Docker Desktop grows its disk image on the host during a build.
            report["host_free_bytes"] = shutil.disk_usage(ROOT).free
            if report["host_free_bytes"] < 4 * 1024 ** 3:
                raise RuntimeError("Less than 4 GiB host space available; skipping Docker build/runtime checks")
            report["docker"] = run(["docker", "version", "--format", "{{json .}}"], ROOT)
            report["compose"] = run(["docker", "compose", "version"], ROOT)
            if report["docker"]["returncode"] != 0 or report["compose"]["returncode"] != 0:
                raise RuntimeError("Docker/Compose preflight failed; runtime evidence unavailable")
            # These invoke unmodified production CLI commands against fixture copies.
            minimal = materialize("minimal", root / "minimal")
            report["observations"]["minimal_generated"] = {
                "dockerize": cli("dockerize", minimal), "validate": cli("validate", minimal),
            }
            base = materialize("existing-compose", root / "existing-compose")
            report["observations"]["existing_configuration"] = {"validate": cli("validate", base)}

            def compose(case, port=None):
                project = prefix + "-" + case
                service = {
                    "image": image,
                    "build": {"context": str(base)},
                    "ports": [f"127.0.0.1:{port or ''}:3000"],
                    "environment": {"NEXT_TELEMETRY_DISABLED": "1"},
                }
                if case in {"missing-env", "startup-failure"}:
                    repo = materialize(case, root / case)
                    service["volumes"] = [{"type": "bind", "source": str(repo / "next.config.mjs"),
                                           "target": "/app/next.config.mjs", "read_only": True}]
                config = root / f"{case}.json"
                config.write_text(json.dumps({"services": {"app": service}}, indent=2))
                command = ["docker", "compose", "-p", project, "-f", str(config)]
                projects.append(command)
                return command

            healthy = compose("healthy")
            # Keep Buildx bookkeeping in the run directory, not ~/.docker/buildx.
            buildx = root / "buildx"
            buildx.mkdir()
            report["build"] = run(healthy + ["build"], root, timeout=300,
                                  extra_env={"BUILDX_CONFIG": str(buildx)})
            if report["build"]["returncode"] != 0:
                raise RuntimeError("Fixture build failed; runtime checks were not run")
            image_built = True
            report["image_id"] = run(["docker", "image", "inspect", image, "--format", "{{.Id}}"], root)
            report["node_npm"] = run(["docker", "run", "--rm", image, "node", "-p", "process.version"], root)
            report["npm"] = run(["docker", "run", "--rm", image, "npm", "--version"], root)
            up = run(healthy + ["up", "-d", "--no-build"], root, timeout=60)
            if up["returncode"] != 0:
                raise RuntimeError("Healthy fixture did not start")
            binding = run(healthy + ["port", "app", "3000"], root)
            address = binding["stdout"].strip()
            if not address.startswith("127.0.0.1:"):
                raise RuntimeError(f"Unexpected fixture port binding: {address}")
            url = f"http://{address}"
            deadline = time.monotonic() + 90
            response = None
            while time.monotonic() < deadline:
                try:
                    with urlopen(url, timeout=3) as http:
                        body = http.read().decode()
                        response = {"status": http.status, "fixture_marker_found": "devops-agent-baseline-ready" in body}
                    if response["status"] == 200 and response["fixture_marker_found"]:
                        break
                except (URLError, OSError):
                    pass
                time.sleep(1)
            report["observations"]["healthy_runtime"] = {
                "up": up, "response": response,
                "agent_http_check": check_application_url(url, timeout=5),
                "services": run(healthy + ["ps", "-a", "--format", "json"], root),
            }
            if not response or response["status"] != 200 or not response["fixture_marker_found"]:
                raise RuntimeError("Healthy fixture failed identity/readiness check")

            # Collide only with our own disposable fixture, never a user's workload.
            conflict = compose("conflict", port=address.rsplit(":", 1)[1])
            conflict_up = run(conflict + ["up", "-d", "--no-build"], root, timeout=60)
            report["observations"]["controlled_port_conflict"] = {
                "up": conflict_up, "original_still_healthy": check_application_url(url, timeout=5),
            }
            if conflict_up["returncode"] in (0, None):
                raise RuntimeError("Controlled port conflict did not produce a bounded failure")

            for case in ("missing-env", "startup-failure"):
                command = compose(case)
                started = run(command + ["up", "-d", "--no-build"], root, timeout=60)
                states = []
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    status = run(command + ["ps", "-a", "--format", "json"], root)
                    text = status["stdout"].strip()
                    states = json.loads(text) if text.startswith("[") else [json.loads(line) for line in text.splitlines()]
                    if states and all(state.get("State") == "exited" for state in states):
                        break
                    time.sleep(1)
                logs = run(command + ["logs", "--no-color", "--tail", "30"], root)
                report["observations"][case] = {"up": started, "states": states, "logs": logs}
                if not states or not all(s.get("State") == "exited" and s.get("ExitCode", 0) != 0 for s in states):
                    raise RuntimeError(f"{case} did not exit unsuccessfully as designed")
        except Exception as error:
            report["errors"].append(f"{type(error).__name__}: {error}")
        finally:
            # Include failed starts: production cleanup currently misses this case.
            for command in reversed(projects):
                result = run(command + ["down", "--volumes", "--remove-orphans"], root, timeout=15)
                report["cleanup"].append(result)
                if result["returncode"] != 0:
                    report["errors"].append("Fixture cleanup failed: " + " ".join(command))
            if image_built:
                result = run(["docker", "image", "rm", image], root)
                report["cleanup"].append(result)
                if result["returncode"] != 0:
                    report["errors"].append("Fixture image cleanup failed")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            encoded = json.dumps(report, indent=2).replace(str(root.resolve()), "<temporary-fixtures>").replace(str(root), "<temporary-fixtures>").replace(str(ROOT), "<repo>")
            # Do not truncate previously saved evidence if a disk-full write fails.
            temporary_output = args.output.with_suffix(args.output.suffix + ".tmp")
            temporary_output.write_text(encoded + "\n")
            temporary_output.replace(args.output)
    print(json.dumps({"output": str(args.output), "errors": report["errors"],
                      "observations": list(report["observations"])}, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
