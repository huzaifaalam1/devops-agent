import re
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import urlparse


IGNORED_DIRECTORIES = {
    ".git",
    ".idea",
    ".vscode",
    "node_modules",
    "vendor",
    "tmp",
    "log",
    "coverage",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
}


SEARCHABLE_SUFFIXES = {
    ".yml",
    ".yaml",
    ".env",
    ".conf",
    ".rb",
    ".json",
    ".toml",
    ".ini",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".py",
}


SEARCHABLE_FILENAMES = {
    "Dockerfile",
    "Caddyfile",
    "Procfile",
    ".env",
    ".env.example",
}


def run_command(
    command: list[str],
    repo_path: Path,
) -> dict:
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


def extract_conflicting_port(
    output: str,
) -> int | None:
    match = re.search(
        r"Bind for (?:0\.0\.0\.0|\[::\]):(\d+) failed",
        output,
    )

    if not match:
        return None

    return int(match.group(1))


def find_compose_project_using_port(
    port: int,
    repo_path: Path,
) -> dict | None:
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

    if (
        not result["success"]
        or not result["stdout"].strip()
    ):
        return None

    line = (
        result["stdout"]
        .strip()
        .splitlines()[0]
    )

    parts = line.split("|", 3)

    if len(parts) != 4:
        return None

    (
        project_name,
        working_dir,
        config_files,
        container_name,
    ) = parts

    if (
        not project_name
        or not working_dir
        or not config_files
    ):
        return None

    compose_files = [
        compose_file.strip()
        for compose_file
        in config_files.split(",")
        if compose_file.strip()
    ]

    return {
        "project_name": project_name,
        "working_dir": working_dir,
        "compose_files": compose_files,
        "container_name": container_name,
        "port": port,
    }


def bring_down_compose_project(
    conflict: dict,
) -> dict:
    working_dir = Path(
        conflict["working_dir"]
    )

    command = [
        "docker",
        "compose",
    ]

    for compose_file in conflict[
        "compose_files"
    ]:
        command.extend(
            [
                "-f",
                compose_file,
            ]
        )

    command.extend(
        [
            "-p",
            conflict["project_name"],
            "down",
        ]
    )

    return run_command(
        command,
        working_dir,
    )


def should_ignore_path(
    path: Path,
    repo_path: Path,
) -> bool:
    try:
        relative_path = path.relative_to(
            repo_path
        )
    except ValueError:
        return True

    return any(
        part in IGNORED_DIRECTORIES
        for part in relative_path.parts
    )


def discover_local_hostnames(
    repo_path: Path,
) -> list[str]:
    """
    Search repository files for local hostnames such as:

        manage.me.localhost
        access.me.localhost
        app.localhost
        localhost

    More-specific *.localhost hostnames are
    returned before plain localhost.
    """

    discovered_hostnames: list[str] = []

    hostname_pattern = re.compile(
        r"(?<![a-zA-Z0-9-])"
        r"((?:[a-zA-Z0-9-]+\.)+localhost|localhost)"
        r"(?![a-zA-Z0-9-])",
        re.IGNORECASE,
    )

    for file_path in repo_path.rglob("*"):
        if not file_path.is_file():
            continue

        if should_ignore_path(
            file_path,
            repo_path,
        ):
            continue

        if (
            file_path.suffix.lower()
            not in SEARCHABLE_SUFFIXES
            and file_path.name
            not in SEARCHABLE_FILENAMES
        ):
            continue

        try:
            content = file_path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except OSError:
            continue

        for match in hostname_pattern.finditer(
            content
        ):
            hostname = (
                match
                .group(1)
                .lower()
                .rstrip(".")
            )

            if (
                hostname
                not in discovered_hostnames
            ):
                discovered_hostnames.append(
                    hostname
                )

    specific_hostnames = [
        hostname
        for hostname in discovered_hostnames
        if hostname != "localhost"
    ]

    return (
        specific_hostnames
        + ["localhost"]
    )


def build_url_candidates(
    repo_path: Path,
    port: int = 3000,
) -> list[str]:
    hostnames = discover_local_hostnames(
        repo_path
    )

    return [
        f"http://{hostname}:{port}"
        for hostname in hostnames
    ]


class NoRedirectHandler(
    HTTPRedirectHandler
):
    """
    Return redirect responses without
    automatically following them.
    """

    def redirect_request(
        self,
        req,
        fp,
        code,
        msg,
        headers,
        newurl,
    ):
        return None


def check_application_url(
    url: str,
    timeout: float = 20.0,
) -> dict:
    """
    Check an application URL without following redirects.

    For *.localhost hostnames, connect directly to 127.0.0.1 while
    preserving the original Host header. This avoids local DNS
    resolution differences while still supporting virtual hosts.
    """

    parsed = urlparse(url)

    hostname = parsed.hostname
    port = parsed.port

    request_url = url
    host_header = None

    if hostname and hostname.endswith(".localhost"):
        request_url = (
            f"{parsed.scheme}://127.0.0.1"
            f":{port or 80}"
            f"{parsed.path or '/'}"
        )

        if parsed.query:
            request_url += f"?{parsed.query}"

        host_header = hostname

        if port:
            host_header += f":{port}"

    opener = build_opener(
        NoRedirectHandler()
    )

    def send_request(method: str):
        headers = {
            "User-Agent": "devops-agent/1.0",
        }

        if host_header:
            headers["Host"] = host_header

        request = Request(
            request_url,
            method=method,
            headers=headers,
        )

        return opener.open(
            request,
            timeout=timeout,
        )

    try:
        try:
            response = send_request("HEAD")

        except HTTPError as error:
            if error.code != 405:
                raise

            response = send_request("GET")

        with response:
            status_code = response.status

            return {
                "url": url,
                "reachable": True,
                "healthy": 200 <= status_code < 300,
                "status_code": status_code,
                "redirect_url": response.headers.get(
                    "Location"
                ),
                "error": None,
            }

    except HTTPError as error:
        status_code = error.code

        return {
            "url": url,
            "reachable": True,
            "healthy": 200 <= status_code < 300,
            "status_code": status_code,
            "redirect_url": error.headers.get(
                "Location"
            ),
            "error": str(error),
        }

    except (
        URLError,
        TimeoutError,
        OSError,
    ) as error:
        return {
            "url": url,
            "reachable": False,
            "healthy": False,
            "status_code": None,
            "redirect_url": None,
            "error": str(error),
        }

def discover_working_url(
    repo_path: Path,
    port: int = 3000,
    attempts: int = 20,
    delay: float = 3.0,
    timeout: float = 20.0,
) -> dict:
    candidates = build_url_candidates(
        repo_path=repo_path,
        port=port,
    )

    localhost_candidate = (
        f"http://localhost:{port}"
    )

    custom_candidates = [
        candidate
        for candidate in candidates
        if candidate
        != localhost_candidate
    ]

    # If the repository declares
    # custom *.localhost hosts,
    # validate those first.
    #
    # Plain localhost is used only when
    # no custom host was discovered.
    candidates_to_check = (
        custom_candidates
        or [localhost_candidate]
    )

    checks: list[dict] = []

    for attempt in range(
        1,
        attempts + 1,
    ):
        for candidate in (
            candidates_to_check
        ):
            check = (
                check_application_url(
                    url=candidate,
                    timeout=timeout,
                )
            )

            check["attempt"] = attempt

            checks.append(
                check
            )

            if check["healthy"]:
                return {
                    "success": True,
                    "url": candidate,
                    "status_code": (
                        check[
                            "status_code"
                        ]
                    ),
                    "redirect_url": (
                        check.get(
                            "redirect_url"
                        )
                    ),
                    "candidates": (
                        candidates
                    ),
                    "checked_candidates": (
                        candidates_to_check
                    ),
                    "checks": checks,
                    "error": None,
                }

        if attempt < attempts:
            time.sleep(
                delay
            )

    reachable_checks = [
        check
        for check in checks
        if check["reachable"]
    ]

    if reachable_checks:
        last_reachable = (
            reachable_checks[-1]
        )

        redirect_detail = ""

        if last_reachable.get(
            "redirect_url"
        ):
            redirect_detail = (
                " Redirect location: "
                f"{last_reachable['redirect_url']}."
            )

        return {
            "success": False,
            "url": (
                last_reachable[
                    "url"
                ]
            ),
            "status_code": (
                last_reachable[
                    "status_code"
                ]
            ),
            "redirect_url": (
                last_reachable.get(
                    "redirect_url"
                )
            ),
            "candidates": candidates,
            "checked_candidates": (
                candidates_to_check
            ),
            "checks": checks,
            "error": (
                "The application responded, "
                "but did not return a successful "
                "2xx status: "
                f"{last_reachable['status_code']}."
                f"{redirect_detail}"
            ),
        }

    return {
        "success": False,
        "url": None,
        "status_code": None,
        "redirect_url": None,
        "candidates": candidates,
        "checked_candidates": (
            candidates_to_check
        ),
        "checks": checks,
        "error": (
            "No discovered application "
            "URL responded."
        ),
    }


def validation_response(
    *,
    success: bool,
    phase: str,
    results: list[dict],
    logs: str = "",
    expected_services: (
        list[str] | None
    ) = None,
    running_services: (
        list[str] | None
    ) = None,
    stopped_services: (
        list[str] | None
    ) = None,
    application_check: (
        dict | None
    ) = None,
) -> dict:
    return {
        "success": success,
        "phase": phase,
        "results": results,
        "logs": logs,
        "expected_services": (
            expected_services
            or []
        ),
        "running_services": (
            running_services
            or []
        ),
        "stopped_services": (
            stopped_services
            or []
        ),
        "application_check": (
            application_check
        ),
    }

def detect_docker_engine_error(
    output: str,
) -> str | None:
    output_lower = (
        output.lower()
    )

    engine_error_patterns = {
        "metadata.db": (
            "Docker Desktop failed while "
            "writing container metadata."
        ),

        "metadata_v2.db": (
            "Docker Desktop failed while "
            "writing BuildKit metadata."
        ),

        "input/output error": (
            "Docker encountered an "
            "input/output error while "
            "accessing its internal storage."
        ),

        "containerd": (
            "Docker's container runtime "
            "encountered an internal error."
        ),

        "snapshotter": (
            "Docker's filesystem snapshotter "
            "encountered an internal "
            "storage error."
        ),

        "docker.sock": (
            "The Docker daemon may not "
            "be running or accessible."
        ),

        (
            "cannot connect to the "
            "docker daemon"
        ): (
            "The Docker daemon is not "
            "running or cannot be reached."
        ),
    }

    for (
        pattern,
        message,
    ) in engine_error_patterns.items():
        if pattern in output_lower:
            return message

    return None


def validate_docker(
    path: str,
    compose_file: str | None = None,
    build: bool = False,
    run: bool = False,
    keep_running: bool = False,
) -> dict:
    repo_path = Path(
        path
    ).resolve()

    if not repo_path.exists():
        return validation_response(
            success=False,
            phase="repository",
            results=[],
            logs=(
                "Repository path does "
                f"not exist: {repo_path}"
            ),
        )

    if not repo_path.is_dir():
        return validation_response(
            success=False,
            phase="repository",
            results=[],
            logs=(
                "Repository path is not "
                f"a directory: {repo_path}"
            ),
        )

    compose_command = [
        "docker",
        "compose",
    ]

    if compose_file:
        compose_command.extend(
            [
                "-f",
                compose_file,
            ]
        )

    results: list[dict] = []

    containers_started = False

    # ---------------------------------------------------------
    # Phase 1: Validate Docker Compose configuration
    # ---------------------------------------------------------

    config_result = run_command(
        compose_command
        + ["config"],
        repo_path,
    )

    results.append(
        config_result
    )

    if not config_result["success"]:
        output = (
            config_result["stderr"]
            or config_result["stdout"]
            or ""
        )

        engine_error = (
            detect_docker_engine_error(
                output
            )
        )

        if engine_error:
            return validation_response(
                success=False,
                phase="docker_engine",
                results=results,
                logs=output,
                application_check={
                    "error": (
                        engine_error
                    ),
                },
            )

        return validation_response(
            success=False,
            phase="config",
            results=results,
            logs=output,
        )

    # ---------------------------------------------------------
    # Phase 2: Build Docker images
    # ---------------------------------------------------------

    if build or run:
        build_result = run_command(
            compose_command
            + ["build"],
            repo_path,
        )

        results.append(
            build_result
        )

        if not build_result[
            "success"
        ]:
            output = (
                build_result["stderr"]
                or build_result["stdout"]
                or ""
            )

            engine_error = (
                detect_docker_engine_error(
                    output
                )
            )

            if engine_error:
                return validation_response(
                    success=False,
                    phase="docker_engine",
                    results=results,
                    logs=output,
                    application_check={
                        "error": (
                            engine_error
                        ),
                    },
                )

            return validation_response(
                success=False,
                phase="build",
                results=results,
                logs=output,
            )

    if not run:
        return validation_response(
            success=True,
            phase=(
                "build"
                if build
                else "config"
            ),
            results=results,
        )

    try:
        # -----------------------------------------------------
        # Phase 3: Start Docker Compose services
        # -----------------------------------------------------

        up_result = run_command(
            compose_command
            + [
                "up",
                "-d",
            ],
            repo_path,
        )

        results.append(
            up_result
        )

        if not up_result["success"]:
            output = (
                up_result["stderr"]
                or up_result["stdout"]
                or ""
            )

            engine_error = (
                detect_docker_engine_error(
                    output
                )
            )

            if engine_error:
                return validation_response(
                    success=False,
                    phase="docker_engine",
                    results=results,
                    logs=output,
                    application_check={
                        "error": (
                            engine_error
                        ),
                    },
                )

            return validation_response(
                success=False,
                phase="startup",
                results=results,
                logs=output,
            )

        containers_started = True

        # Small stabilization delay.
        # Readiness is handled by the HTTP polling loop.
        time.sleep(3)

        # -----------------------------------------------------
        # Phase 4: Verify expected services are running
        # -----------------------------------------------------

        expected_result = run_command(
            compose_command
            + [
                "config",
                "--services",
            ],
            repo_path,
        )

        results.append(
            expected_result
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

        results.append(
            running_result
        )

        status_result = run_command(
            compose_command
            + [
                "ps",
                "-a",
            ],
            repo_path,
        )

        results.append(
            status_result
        )

        logs_result = run_command(
            compose_command
            + [
                "logs",
                "--no-color",
                "--tail",
                "100",
            ],
            repo_path,
        )

        logs = (
            logs_result["stdout"]
            or logs_result["stderr"]
        )

        if not expected_result[
            "success"
        ]:
            return validation_response(
                success=False,
                phase="runtime",
                results=results,
                logs=logs,
            )

        if not running_result[
            "success"
        ]:
            return validation_response(
                success=False,
                phase="runtime",
                results=results,
                logs=logs,
            )

        expected_services = [
            service.strip()
            for service
            in (
                expected_result[
                    "stdout"
                ].splitlines()
            )
            if service.strip()
        ]

        running_services = [
            service.strip()
            for service
            in (
                running_result[
                    "stdout"
                ].splitlines()
            )
            if service.strip()
        ]

        stopped_services = sorted(
            set(expected_services)
            - set(running_services)
        )

        if stopped_services:
            return validation_response(
                success=False,
                phase="runtime",
                results=results,
                logs=logs,
                expected_services=(
                    expected_services
                ),
                running_services=(
                    running_services
                ),
                stopped_services=(
                    stopped_services
                ),
            )

        # -----------------------------------------------------
        # Phase 5: Application readiness / HTTP validation
        # -----------------------------------------------------

        application_check = (
            discover_working_url(
                repo_path=repo_path,
                port=3000,
            )
        )

        if not application_check[
            "success"
        ]:
            return validation_response(
                success=False,
                phase="application",
                results=results,
                logs=logs,
                expected_services=(
                    expected_services
                ),
                running_services=(
                    running_services
                ),
                stopped_services=[],
                application_check=(
                    application_check
                ),
            )

        return validation_response(
            success=True,
            phase="application",
            results=results,
            logs=logs,
            expected_services=(
                expected_services
            ),
            running_services=(
                running_services
            ),
            stopped_services=[],
            application_check=(
                application_check
            ),
        )

    finally:
        if (
            containers_started
            and not keep_running
        ):
            run_command(
                compose_command
                + ["down"],
                repo_path,
            )