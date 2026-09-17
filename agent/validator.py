"""Bounded, isolated Docker validation with container-owned readiness evidence."""

import json
import os
import signal
import socket
import errno
import shlex
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


def run_command(command, repo_path, timeout=30):
    result = {"command": " ".join(command), "success": False, "stdout": "", "stderr": "", "returncode": None}
    process = None
    try:
        process = subprocess.Popen(command, cwd=repo_path, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, start_new_session=True)
        stdout, stderr = process.communicate(timeout=timeout)
        result.update(success=process.returncode == 0, stdout=stdout, stderr=stderr, returncode=process.returncode)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        if process:
            # Kill the command's process group, including shell/helper descendants.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
        if isinstance(error, KeyboardInterrupt):
            raise
        result.update(stderr=f"Command timed out after {timeout:.1f} seconds.", timed_out=True)
    except OSError:
        result.update(stderr="Executable is missing or cannot be started.", host_error=True)
    return result


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check_application_url(url, timeout=5.0, follow_redirects=False):
    """Probe without proxies; optionally follow only same-origin redirects.

    No response body is needed for readiness. A reachable 401/403 is not healthy.
    """
    original = urlparse(url)
    current = url
    deadline = time.monotonic() + timeout
    redirects = []
    result = {"url": url, "reachable": False, "healthy": False, "status_code": None,
              "redirect_url": None, "error": None, "redirects": redirects}
    opener = build_opener(ProxyHandler({}), NoRedirectHandler())
    for _ in range(6):
        method = "HEAD"
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result["error"] = "HTTP readiness deadline exceeded."
                return result
            try:
                response = opener.open(Request(current, method=method, headers={"User-Agent": "devops-agent"}), timeout=remaining)
            except HTTPError as error:
                response = error
            except (URLError, OSError, ValueError) as error:
                result["error"] = str(error)
                return result
            with response:
                status = response.code
                location = response.headers.get("Location")
            result.update(reachable=True, status_code=status, healthy=200 <= status < 300,
                          redirect_url=location, final_url=current)
            if status == 405 and method == "HEAD":
                method = "GET"
                continue
            break
        if result["healthy"]:
            return result
        if follow_redirects and status in (301, 302, 303, 307, 308) and location:
            redirected = urljoin(current, location)
            parsed = urlparse(redirected)
            if (parsed.scheme, parsed.hostname, parsed.port) != (original.scheme, original.hostname, original.port) or parsed.username or parsed.password:
                result["error"] = "Redirect left the verified container endpoint; it was not followed."
                return result
            redirects.append(redirected)
            current = redirected
            continue
        result["error"] = ("Authentication is required; choose an unauthenticated readiness path."
                           if status in (401, 403) else f"Readiness endpoint returned HTTP {status}.")
        return result
    result["error"] = "Readiness redirect limit exceeded."
    return result


class ValidationFailure(Exception):
    def __init__(self, phase, message, action):
        super().__init__(message)
        self.phase, self.action = phase, action


def fail(phase, message, action="Inspect the reported stage and correct the configuration before retrying."):
    raise ValidationFailure(phase, message, action)


def isolated_config(config, project, repo):
    """Reject shared-resource configurations before creating any Docker resources."""
    services = config.get("services")
    if not isinstance(services, dict) or not services:
        fail("config", "Compose contains no services.")
    for kind in ("volumes", "networks", "secrets", "configs"):
        for resource in (config.get(kind) or {}).values():
            if resource and (resource.get("external") or resource.get("name") or resource.get("driver_opts")):
                fail("isolation", f"Explicit/shared {kind} cannot be isolated safely.", "Use a development configuration without externally named resources.")
    # Compose inserts an explicit name even for its automatic default network.
    # The caller removes that single implicit default before this check.
    for name, service in services.items():
        if any(service.get(key) for key in ("container_name", "network_mode", "pid", "ipc", "privileged", "devices", "external_links", "volumes_from", "post_start", "pre_stop", "develop")):
            fail("isolation", f"Service {name} uses unsupported shared-state or lifecycle options.")
        for mount in service.get("volumes", []):
            if not isinstance(mount, dict):
                fail("isolation", "Unresolved mount syntax.")
            if mount.get("type") == "bind":
                source = Path(mount.get("source", "")).resolve()
                if not mount.get("read_only") or not source.is_file() or not source.is_relative_to(repo):
                    fail("isolation", f"Service {name} has a writable, external, or non-file bind mount.", "Use only read-only configuration files inside the application directory for validation.")
        if isinstance(service.get("build"), dict) and service["build"].get("tags"):
            fail("isolation", "Additional build tags could replace unrelated images.")
        if service.get("build"):
            # Never replace a user's named image tag while validating a build.
            service["image"] = f"{project}-{name}:validation"
    config["name"] = project
    return config


def check_published_ports(config):
    """Fail before startup if an explicitly requested local host port is occupied."""
    for item in config["services"].values():
        for port in item.get("ports", []):
            published = str(port.get("published", "0"))
            if published in ("", "0"):
                continue
            if not published.isdigit():
                fail("application", "Published port ranges require explicit single-port configuration.")
            host = port.get("host_ip") or "0.0.0.0"
            family = socket.AF_INET6 if ":" in host else socket.AF_INET
            kind = socket.SOCK_DGRAM if port.get("protocol") == "udp" else socket.SOCK_STREAM
            with socket.socket(family, kind) as probe:
                try:
                    probe.bind((host, int(published)))
                except OSError as error:
                    if error.errno == errno.EADDRINUSE:
                        fail("startup", f"Host port {published} is already in use.", "Choose an available host port or stop its owner yourself; validation will not stop another workload.")
                    fail("host", "Cannot check the requested local port binding.", "Check local host binding and network permissions.")


def service_snapshot(containers, services, project):
    records = {}
    ready = True
    for container in containers:
        labels = container.get("Config", {}).get("Labels") or {}
        name = labels.get("com.docker.compose.service")
        if labels.get("com.docker.compose.project") != project or name not in services:
            fail("ownership", "Container ownership does not match the validation project.")
        if name in records:
            fail("services", "Replicated services require an explicit readiness policy.")
        state = container.get("State") or {}
        health = (state.get("Health") or {}).get("Status")
        if state.get("Status") in ("exited", "dead", "restarting") or container.get("RestartCount", 0):
            fail("services", f"Service {name} exited or restarted during validation.", "Inspect this service's startup requirements and logs.")
        has_check = services[name].get("healthcheck", {})
        check_enabled = has_check and not has_check.get("disable") and has_check.get("test") != ["NONE"]
        if not state.get("Running") or state.get("Paused") or (health is not None and health != "healthy") or (check_enabled and health != "healthy"):
            ready = False
        records[name] = {"id": container["Id"], "state": state.get("Status"), "health": health,
                         "ports": container.get("NetworkSettings", {}).get("Ports") or {}}
    if set(records) != set(services):
        ready = False
    return records, ready


def application_endpoint(records, service, container_port, health_path):
    bindings = records[service]["ports"].get(f"{container_port}/tcp") or []
    endpoints = set()
    for binding in bindings:
        host = binding.get("HostIp")
        if host not in ("0.0.0.0", "127.0.0.1", "::", "::1", ""):
            fail("application", "Published endpoint is not a local loopback/wildcard binding.")
        address = "[::1]" if host in ("::", "::1") else "127.0.0.1"
        port = binding.get("HostPort", "")
        if not str(port).isdigit() or not 1 <= int(port) <= 65535:
            fail("application", "Published port is invalid.")
        endpoints.add(f"http://{address}:{port}{health_path}")
    if len(endpoints) == 2 and len({urlparse(u).port for u in endpoints}) == 1:
        endpoints = {u for u in endpoints if urlparse(u).hostname == "127.0.0.1"}
    if len(endpoints) != 1:
        fail("application", "Cannot identify one published HTTP endpoint for the selected service.", "Publish one TCP port or select an explicit container port.")
    return endpoints.pop()


def validate_docker(path, compose_file=None, build=False, run=False, keep_running=False,
                    service=None, container_port=None, health_path="/", timeout=300.0,
                    readiness_timeout=90.0):
    repo = Path(path).resolve()
    report = {"success": False, "phase": "repository", "results": [], "logs": "",
              "expected_services": [], "running_services": [], "stopped_services": [],
              "application_check": None, "stages": [], "cleanup": {"status": "not_needed"},
              "verified": [], "unverified": ["Business correctness and production readiness"],
              "environment_state": "not_started"}
    if not repo.is_dir():
        report["error"] = "Select an existing application directory."
        return report
    if timeout <= 0 or readiness_timeout <= 0 or (keep_running and not run):
        report.update(phase="options", error="Timeouts must be positive; --keep-running requires --run.")
        return report
    if not health_path.startswith("/") or health_path.startswith("//") or "#" in health_path or any(ord(c) < 32 for c in health_path):
        report.update(phase="options", error="Health path must be a local absolute HTTP path.")
        return report
    deadline = time.monotonic() + timeout
    project = "devops-validation-" + uuid.uuid4().hex[:12]
    report["project"] = project
    command = ["docker", "compose", "--project-directory", str(repo), "-p", project]
    if compose_file:
        selected = (repo / compose_file).resolve()
        if not selected.is_relative_to(repo):
            report.update(phase="config", error="Compose file must be inside the selected repository.")
            return report
        command += ["-f", str(selected)]
    original_command = list(command)
    attempted_start = False
    attempted_build = False
    owned_images = []

    def execute(args, phase, sensitive=False, cap=30):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            fail(phase, "Overall validation deadline exceeded.", "Increase --timeout only after inspecting the stalled stage.")
        result = run_command(args, repo, timeout=min(cap, remaining))
        report["results"].append({**result, "stdout": "[structured configuration omitted]" if sensitive else result["stdout"][-8000:], "stderr": result["stderr"][-8000:]})
        if not result["success"]:
            error = result["stderr"] or result["stdout"] or "Command failed."
            if result.get("host_error"):
                fail("host", error, "Install Docker CLI and verify executable permissions.")
            if any(marker in error.lower() for marker in ("cannot connect to the docker daemon", "docker.sock", "input/output error", "no space left on device", "metadata.db")):
                fail("docker_engine", error[-2000:], "Check Docker engine health and available storage before retrying.")
            fail(phase, error[-2000:], "Inspect the command failure and retry after correcting it.")
        return result["stdout"]

    def snapshot(config):
        ids = execute(command + ["ps", "--all", "--quiet"], "services").split()
        if not ids:
            return {}, False
        containers = json.loads(execute(["docker", "inspect", *ids], "services", sensitive=True))
        return service_snapshot(containers, config["services"], project)

    def stage(name):
        report["stages"].append({"phase": name, "success": True})
        report["verified"].append(name)

    # Resolved config can contain secrets; keep it only in a mode-0600 temporary file.
    with tempfile.TemporaryDirectory(prefix="devops-validation-") as temporary:
        try:
            raw = execute(command + ["config", "--format", "json"], "config", sensitive=True)
            config = json.loads(raw)
            stage("config")
            if not build and not run:
                report.update(success=True, phase="config")
                report["unverified"].append("Image build, services and application readiness")
                return report
            endpoint = os.environ.get("DOCKER_HOST") or json.loads(execute(["docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"], "docker_engine"))
            if not isinstance(endpoint, str) or not endpoint.startswith(("unix://", "npipe://")):
                fail("host", "Runtime validation requires a local Docker engine.", "Select a local Docker context; remote-host readiness is not supported.")
            # Compose normalizes its implicit default network name from -p. Only
            # remove the exact run-owned name, never an arbitrary custom name.
            default = (config.get("networks") or {}).get("default")
            if default and default.get("name") == project + "_default" and not default.get("external"):
                default.pop("name")
            config = isolated_config(config, project, repo)
            report["expected_services"] = sorted(config["services"])
            if run:
                candidates = [name for name, item in config["services"].items() if item.get("ports")]
                service = service or (candidates[0] if len(candidates) == 1 else None)
                if service not in config["services"]:
                    fail("application", "Choose the application service with --service.")
                ports = {int(p["target"]) for p in config["services"][service].get("ports", []) if p.get("protocol", "tcp") == "tcp"}
                container_port = container_port or (next(iter(ports)) if len(ports) == 1 else None)
                if container_port not in ports:
                    fail("application", "Choose a published TCP container port with --container-port.")
                report.update(application_service=service, container_port=container_port)
                check_published_ports(config)
            staged = Path(temporary) / "compose.json"
            with staged.open("x") as stream:
                os.chmod(staged, 0o600)
                json.dump(config, stream)
            command = ["docker", "compose", "--project-directory", str(repo), "-p", project, "-f", str(staged)]
            owned_images = [s["image"] for s in config["services"].values() if s.get("build")]
            if owned_images:
                attempted_build = True
                execute(command + ["build"], "build", cap=timeout)
                stage("build")
            else:
                report["stages"].append({"phase": "build", "success": True, "status": "not_required"})
                report["unverified"].append("No build definitions; no images were built")
            if not run:
                report.update(success=True, phase="build")
                report["unverified"].append("Services and application readiness")
            else:
                attempted_start = True  # Partial startup must be cleaned up too.
                report["environment_state"] = "startup_attempted"
                execute(command + ["up", "-d", "--no-build"], "startup", cap=60)
                stage("startup")
                readiness_deadline = min(deadline, time.monotonic() + readiness_timeout)
                deadline = readiness_deadline
                last_phase = "services"
                while time.monotonic() < readiness_deadline:
                    records, ready = snapshot(config)
                    report["service_states"] = records
                    report["running_services"] = sorted(k for k, v in records.items() if v["state"] == "running")
                    report["stopped_services"] = sorted(set(config["services"]) - set(report["running_services"]))
                    if ready:
                        last_phase = "application"
                        url = application_endpoint(records, service, container_port, health_path)
                        check = check_application_url(url, timeout=max(.01, min(5, readiness_deadline - time.monotonic())), follow_redirects=True)
                        report["application_check"] = {**check, "success": check["healthy"], "container_id": records[service]["id"]}
                        if check["healthy"]:
                            # A second snapshot prevents a successful HTTP response
                            # from hiding a crash or replacement during the probe.
                            time.sleep(min(.25, max(0, readiness_deadline - time.monotonic())))
                            after, still_ready = snapshot(config)
                            if time.monotonic() > readiness_deadline:
                                break
                            if not still_ready or after != records:
                                fail("services", "Container state or port ownership changed during the HTTP check.")
                            dependencies = {name: {"state": record["state"], "health": record["health"]}
                                            for name, record in records.items() if name != service}
                            report["dependency_checks"] = dependencies
                            if dependencies:
                                stage("dependencies")
                                if any(item["health"] is None for item in dependencies.values()):
                                    report["unverified"].append("Dependencies without healthchecks: only running state was verified")
                                report["unverified"].append("Application-to-dependency transactions beyond the HTTP readiness response")
                            else:
                                report["stages"].append({"phase": "dependencies", "success": True, "status": "not_required"})
                            stage("services")
                            stage("application")
                            report.update(success=True, phase="application")
                            break
                    time.sleep(min(.5, max(0, readiness_deadline - time.monotonic())))
                if not report["success"]:
                    detail = (report.get("application_check") or {}).get("error") or "Services did not become ready."
                    fail(last_phase, "Readiness deadline exceeded. " + detail, "Inspect service health or select an unauthenticated --health-path.")
        except KeyboardInterrupt:
            report.update(success=False, phase="cancelled", error="Validation cancelled; cleanup was attempted.")
        except ValidationFailure as error:
            report.update(success=False, phase=error.phase, error=str(error), next_action=error.action)
        except (ValueError, KeyError, TypeError, OSError) as error:
            report.update(success=False, phase="configuration_data", error="Docker returned invalid data or temporary configuration could not be written.", next_action="Check Docker/Compose versions, configuration, and disk space.")
        finally:
            preserve = bool(report["success"] and run and keep_running)
            if preserve:
                report["environment_state"] = "running"
                report["cleanup"] = {"status": "kept_running", "project": project,
                                     "stop_command": shlex.join(original_command + ["down", "--volumes"])}
                report["unverified"].append("Future health after validation returns")
            elif attempted_start or attempted_build:
                cleanup = []
                if attempted_start and not report["success"]:
                    logs = run_command(command + ["logs", "--no-color", "--tail", "50"], repo, timeout=10)
                    report["logs"] = (logs["stdout"] or logs["stderr"])[-8000:]
                if attempted_start:
                    cleanup.append(run_command(command + ["down", "--volumes", "--timeout", "5"], repo, timeout=15))
                    remaining = run_command(["docker", "ps", "--all", "--quiet", "--filter", f"label=com.docker.compose.project={project}"], repo, timeout=10)
                    cleanup.append(remaining)
                else:
                    remaining = {"success": True, "stdout": ""}
                for image in owned_images:
                    removed = run_command(["docker", "image", "rm", image], repo, timeout=10)
                    if not removed["success"] and "No such image" in removed["stderr"]:
                        removed["success"] = True
                    cleanup.append(removed)
                clean = all(r["success"] for r in cleanup) and not remaining["stdout"].strip()
                report["cleanup"] = {"status": "complete" if clean else "failed", "results": cleanup}
                report["environment_state"] = "stopped" if clean else "unknown"
                if not clean:
                    report["primary_phase"] = report["phase"]
                    report.update(success=False, phase="cleanup", next_action=f"Inspect resources labeled com.docker.compose.project={project}; cleanup could not be verified.")
                report["unverified"].append("Shared image/build cache is retained")
            if not report["success"]:
                report["stages"].append({"phase": report["phase"], "success": False})
    return report
