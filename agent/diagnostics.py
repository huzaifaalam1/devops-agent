def diagnose_failure(validation_result: dict, context: dict | None = None,) -> dict | None:
    if validation_result["success"]:
        return None

    logs = validation_result.get("logs", "") or ""

    outputs = []

    for result in validation_result.get("results", []):
        outputs.append(result.get("stdout", "") or "")
        outputs.append(result.get("stderr", "") or "")

    evidence_text = "\n".join(outputs + [logs])
    evidence_lower = evidence_text.lower()

    if (
        "bundler::gemnotfound" in evidence_lower
        or "could not find" in evidence_lower
        and "locally installed gems" in evidence_lower
    ):
        return {
            "type": "ruby_dependencies",
            "summary": "Bundler could not find required Ruby gems.",
            "evidence": [
                "Bundler::GemNotFound",
                "Required gems are missing from the container environment.",
            ],
            "likely_causes": [
                "Installed gems do not match Gemfile.lock.",
                "A persisted bundle volume may contain stale or corrupted gems.",
                "The Docker image may not have installed the current dependencies.",
            ],
            "suggested_actions": [
                "Check whether /usr/local/bundle is backed by a Docker volume.",
                "Reinstall the bundle dependencies.",
                "Rebuild the application image without stale dependency state.",
            ],
        }

    if "address already in use" in evidence_lower or "port is already allocated" in evidence_lower:
        return {
            "type": "port_conflict",
            "summary": "A required host port is already in use.",
            "evidence": [
                "Docker reported that a requested port could not be bound.",
            ],
            "likely_causes": [
                "Another container or local process is already using the port.",
            ],
            "suggested_actions": [
                "Identify the process or Compose project using the port.",
                "Stop it or configure this application to use another host port.",
            ],
        }

    if (
        "connection refused" in evidence_lower
        or "could not connect to server" in evidence_lower
    ):
        return {
            "type": "connection_failure",
            "summary": "The application could not connect to a required service.",
            "evidence": [
                "A connection attempt was refused.",
            ],
            "likely_causes": [
                "A dependency may not be running.",
                "The configured hostname or port may be incorrect.",
                "The application may have started before its dependency was ready.",
            ],
            "suggested_actions": [
                "Check the status of dependent services.",
                "Check service hostnames and ports.",
                "Check Compose dependency and health-check configuration.",
            ],
        }

    if (
        "environment variable" in evidence_lower
        and (
            "missing" in evidence_lower
            or "required" in evidence_lower
        )
    ):
        return {
            "type": "missing_environment",
            "summary": "The application appears to be missing required environment configuration.",
            "evidence": [
                "The application reported a missing or required environment variable.",
            ],
            "likely_causes": [
                "The .env file may be missing.",
                "A required variable may not be defined.",
                "Compose may not be loading the expected environment file.",
            ],
            "suggested_actions": [
                "Check the application's required environment variables.",
                "Check Compose env_file and environment configuration.",
                "Compare the current environment against .env.example if available.",
            ],
        }

    return {
        "type": "unknown",
        "summary": "The application failed, but no known failure pattern was recognized.",
        "evidence": [],
        "likely_causes": [],
        "suggested_actions": [
            "Inspect the failed service logs.",
        ],
    }