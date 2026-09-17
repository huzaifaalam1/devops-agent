"""Deterministic troubleshooting advice; never executes repairs or log instructions."""

# Each entry includes a concrete action, its impact, and a resolution check.
CATALOG = {
    "port_conflict": (
        "A requested host port is occupied.",
        "Another local process or container owns the requested binding.",
        "Identify the owner of the reported port, then change this project's Compose published host port to an available port. Keep the container target port unchanged.",
        "The application's local URL changes; unrelated workloads stay running.",
        "Rerun validate --run and require successful binding plus HTTP readiness on the newly inspected host port."),
    "missing_environment": (
        "Required environment configuration is missing.",
        "A required value is absent or is not loaded into the application.",
        "Compare the reported variable names with .env.example and the app's configuration; supply actual local values in the expected environment file and verify its Compose mount/env_file configuration.",
        "Changes local application configuration; do not invent credentials or commit secret values.",
        "Rerun analyze to clear environment blockers, then validate --run; require the missing-variable error to disappear and HTTP readiness to pass."),
    "dependency_installation": (
        "Dependency installation failed during the image build.",
        "The package manager could not resolve or install the locked dependencies; the specific error determines whether this is lockfile, registry, authentication, or compatibility related.",
        "Inspect the first package-manager error in the failed build output. For lockfile mismatch, reconcile package.json and package-lock.json with the project's npm version; for registry/network/auth errors, correct that access before rebuilding.",
        "May update the lockfile or local registry configuration; review lockfile changes. Do not delete the lockfile or disable integrity checks as a generic fix.",
        "Rerun validate --build and require the dependency-install layer to succeed; then validate --run to check startup separately."),
    "connection_failure": (
        "A connection attempt failed.",
        "A dependency may be unavailable, listening on another address, or still starting; the message alone does not identify the failing service.",
        "Use the error's host and port to identify the dependency. Check that service's state and health, then compare the app's configured address with its Compose service name and container port.",
        "May change a dependency address or readiness configuration; inspect before restarting anything.",
        "Retry the same application operation that failed, then validate --run; require the connection error to disappear and service/HTTP checks to pass."),
    "docker_unavailable": (
        "The Docker CLI or engine is unavailable.",
        "Docker may be stopped, missing, inaccessible, or selected through the wrong context.",
        "Run docker version and docker context show. Start the local Docker engine if stopped; select the intended local context or correct CLI/socket permissions if those checks fail.",
        "Starting Docker or changing its context affects the local environment; no application files need changing.",
        "Require docker version to report both client and server, then rerun the original validation command."),
    "docker_storage": (
        "Docker reported a storage or I/O failure.",
        "Host or Docker storage may be full or unhealthy; this is not evidence of an application defect.",
        "Check host free space and docker system df. Review specific unused resources before removing anything, and restore engine/storage health; do not run a blanket prune.",
        "Storage cleanup can delete data; select resources deliberately. No automatic deletion is performed.",
        "Require Docker inspection to work without storage errors, then rerun the failed build or validation."),
    "ruby_dependencies": (
        "Bundler could not find required Ruby gems.",
        "Installed gems may not match Gemfile.lock or the image's dependency layer.",
        "Compare Gemfile.lock with the image's bundle installation and any bundle mount; correct the dependency installation before rebuilding.",
        "May rebuild dependency layers. Ruby runtime support remains outside the first-release scope.",
        "Verify bundle check in the project's own supported workflow; a matching diagnostic does not certify Ruby validation support."),
    "http_authentication": (
        "The readiness endpoint requires authentication.",
        "HTTP 401/403 means the endpoint is reachable but does not prove unauthenticated readiness.",
        "Select an existing unauthenticated readiness route with --health-path; do not disable application authentication.",
        "Changes the probe path only.",
        "Rerun validate --run --health-path /your-readiness-route and require a final 2xx response from the owned endpoint."),
    "cleanup_failure": (
        "Validation could not verify resource cleanup.",
        "The run's resources may remain after shutdown failed or inventory could not be read.",
        "Inspect cleanup.results and the reported validation project label. Restore Docker access, then remove only that run's resources after confirming ownership.",
        "Stops/removes the identified validation environment; the original failure may still require a separate fix.",
        "Require scoped shutdown to succeed and no containers to remain with the reported project label."),
    "unknown": (
        "Validation failed without a supported diagnosis.",
        "The available evidence is insufficient to identify a cause.",
        "Inspect the failed stage, command stderr, application check, and service logs with --verbose or --json. Find the earliest failing operation and reproduce it in the project's normal workflow before editing configuration.",
        "Inspection only; no repair is justified by this diagnosis.",
        "After identifying and correcting the cause, rerun the original validation command and require all requested stages and cleanup to pass."),
}


def diagnose_failure(validation_result: dict, context: dict | None = None) -> dict | None:
    if validation_result.get("success"):
        return None
    phase = validation_result.get("phase", "unknown")
    sources = [("error", validation_result.get("error", ""))]
    for i, result in enumerate(validation_result.get("results", [])):
        # Successful commands may contain stale warnings or arbitrary app text.
        if not result.get("success", False):
            sources.extend((f"results[{i}].{key}", result.get(key, "")) for key in ("stderr", "stdout"))
    sources.append(("logs", validation_result.get("logs", "")))
    project = validation_result.get("project")
    project = project if isinstance(project, dict) else {}
    missing_configuration = []
    for i, blocker in enumerate(project.get("blockers", [])):
        if blocker.get("code") == "environment_missing":
            missing_configuration.append({"source": f"project.blockers[{i}]", "excerpt": blocker.get("message", "")[:500]})
    lines = [(source, line[:500]) for source, value in sources if isinstance(value, str)
             for line in value[-16000:].splitlines() if line.strip()]

    def matching(*patterns):
        return [{"source": source, "excerpt": line} for source, line in lines
                if any(pattern in line.lower() for pattern in patterns)][:3]

    category, confidence, evidence = "unknown", "low", []
    rules = [
        ("docker_storage", ("no space left on device", "input/output error", "metadata.db")),
        ("docker_unavailable", ("cannot connect to the docker daemon", "is the docker daemon running", "executable is missing", "permission denied while trying to connect to the docker")),
        ("port_conflict", ("address already in use", "port is already allocated", "is already in use")),
        ("missing_environment", ("environment variable",)),
        ("ruby_dependencies", ("bundler::gemnotfound", "locally installed gems")),
        ("dependency_installation", ("eresolve", "eusage", "etarget", "eintegrity", "ebadengine", "npm error code e401", "npm error code e404", "npm ci can only install")),
        ("connection_failure", ("connection refused", "could not connect to server", "econnrefused", "enotfound")),
    ]
    if phase == "cleanup":
        category, confidence = "cleanup_failure", "high"
        evidence = [{"source": "cleanup.status", "excerpt": str(validation_result.get("cleanup", {}).get("status", "unknown"))}]
    elif missing_configuration:
        category, confidence, evidence = "missing_environment", "high", missing_configuration[:3]
    else:
        for candidate, patterns in rules:
            matches = matching(*patterns)
            if candidate == "port_conflict":
                matches = [e for e in matches if "port" in e["excerpt"].lower() or "address already in use" in e["excerpt"].lower()]
            if candidate == "missing_environment":
                matches = [e for e in matches if any(w in e["excerpt"].lower() for w in ("missing", "required", "not set"))]
            if candidate == "dependency_installation" and phase not in ("build", "unknown"):
                continue
            if matches:
                category, evidence = candidate, matches
                confidence = "medium" if candidate in ("connection_failure", "dependency_installation", "ruby_dependencies") else "high"
                break
        check = validation_result.get("application_check") or {}
        if category == "unknown" and check.get("status_code") in (401, 403):
            category, confidence = "http_authentication", "high"
            evidence = [{"source": "application_check.status_code", "excerpt": str(check["status_code"])}]
    if category == "unknown":
        check = validation_result.get("application_check") or {}
        if check.get("error"):
            lines.append(("application_check.error", str(check["error"])[:500]))
    if not evidence:
        evidence = [{"source": s, "excerpt": line} for s, line in lines[:3]]
    summary, cause, action, impact, verification = CATALOG[category]
    return {"type": category, "phase": phase, "summary": summary,
            "symptoms": [e["excerpt"] for e in evidence], "evidence": evidence,
            "confidence": confidence, "uncertainty": "Confidence describes the observed failure category, not a proven root cause. Multiple failures may coexist; this is the first supported diagnosis.",
            "likely_causes": [cause], "suggested_actions": [action],
            "expected_impact": impact, "verification": verification,
            "automatic_repair": False, "details_hint": "Use --verbose for captured command output/logs or --json for the full report."}
