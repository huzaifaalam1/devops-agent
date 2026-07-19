import subprocess
import time
import re
from pathlib import Path


def run_command(command: list[str], repo_path: Path):
    result = subprocess.run(
        command,
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    return {
        "command": " ".join(command),
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }

def extract_conflicting_port(output: str) -> int | None:
    match = re.search(
        r"Bind for (?:0\.0\.0\.0|\[::\]):(\d+) failed",
        output,
    )

    if not match:
        return None

    return int(match.group(1))


def find_compose_project_using_port(port: int, repo_path: Path):
    result = run_command(
        [
            "docker",
            "ps",
            "--filter",
            f"publish={port}",
            "--format",
            (
                '{{.Label "com.docker.compose.project"}}|'
                '{{.Label "com.docker.compose.project.working_dir"}}|'
                '{{.Label "com.docker.compose.project.config_files"}}|'
                "{{.Names}}"
            ),
        ],
        repo_path,
    )

    if not result["success"] or not result["stdout"].strip():
        return None

    line = result["stdout"].strip().splitlines()[0]
    parts = line.split("|", 3)

    if len(parts) != 4:
        return None

    project_name, working_dir, config_files, container_name = parts

    if not project_name or not working_dir or not config_files:
        return None

    # Docker may store multiple compose files separated by commas.
    compose_files = [
        compose_file.strip()
        for compose_file in config_files.split(",")
        if compose_file.strip()
    ]

    return {
        "project_name": project_name,
        "working_dir": working_dir,
        "compose_files": compose_files,
        "container_name": container_name,
        "port": port,
    }


def bring_down_compose_project(conflict: dict):
    working_dir = Path(conflict["working_dir"])

    command = ["docker", "compose"]

    for compose_file in conflict["compose_files"]:
        command.extend(["-f", compose_file])

    command.extend(
        [
            "-p",
            conflict["project_name"],
            "down",
        ]
    )

    return run_command(command, working_dir)

def validate_docker(
    path: str,
    compose_file: str | None = None,
    build: bool = False,
    run: bool = False,
    keep_running: bool = False,
):
    repo_path = Path(path).resolve()

    compose_command = ["docker", "compose"]

    if compose_file:
        compose_command.extend(["-f", compose_file])

    results = []
    containers_started = False

    # Always validate the Compose configuration first.
    config_result = run_command(
        compose_command + ["config"],
        repo_path,
    )
    results.append(config_result)

    if not config_result["success"]:
        return {
            "success": False,
            "phase": "config",
            "results": results,
            "logs": "",
            "expected_services": [],
            "running_services": [],
        }

    if build or run:
        build_result = run_command(
            compose_command + ["build"],
            repo_path,
        )
        results.append(build_result)

        if not build_result["success"]:
            return {
                "success": False,
                "phase": "build",
                "results": results,
                "logs": "",
                "expected_services": [],
                "running_services": [],
            }

    if not run:
        return {
            "success": True,
            "phase": "build" if build else "config",
            "results": results,
            "logs": "",
            "expected_services": [],
            "running_services": [],
        }

    try:
        up_result = run_command(
            compose_command + ["up", "-d"],
            repo_path,
        )
        results.append(up_result)

        if not up_result["success"]:
            return {
                "success": False,
                "phase": "startup",
                "results": results,
                "logs": "",
                "expected_services": [],
                "running_services": [],
            }

        containers_started = True

        # Give containers a moment to start or crash.
        time.sleep(5)

        expected_result = run_command(
            compose_command + ["config", "--services"],
            repo_path,
        )

        running_result = run_command(
            compose_command
            + [
                "ps",
                "--services",
                "--filter",
                "status=running",
            ],
            repo_path,
        )

        status_result = run_command(
            compose_command + ["ps", "-a"],
            repo_path,
        )
        results.append(status_result)

        logs_result = run_command(
            compose_command + ["logs", "--no-color", "--tail", "100"],
            repo_path,
        )

        expected_services = [
            service.strip()
            for service in expected_result["stdout"].splitlines()
            if service.strip()
        ]

        running_services = [
            service.strip()
            for service in running_result["stdout"].splitlines()
            if service.strip()
        ]

        stopped_services = set(expected_services) - set(running_services)
        success = not stopped_services

        return {
            "success": success,
            "phase": "runtime",
            "results": results,
            "logs": logs_result["stdout"] or logs_result["stderr"],
            "expected_services": expected_services,
            "running_services": running_services,
        }

    finally:
        if containers_started and not keep_running:
            run_command(
                compose_command + ["down"],
                repo_path,
            )