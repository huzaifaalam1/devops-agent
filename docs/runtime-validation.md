# Runtime validation — step 5

Validation now reports separate configuration, image build, startup, dependency,
service, and application evidence. Configuration-only success never claims the
application ran. Runtime success requires every expected service to be running,
every observed or declared healthcheck to be healthy, and the selected HTTP
endpoint to return 2xx. Exited, restarting, replaced, or wrongly owned containers
fail validation. Dependencies without healthchecks prove running state only;
application-to-dependency transactions remain unverified beyond the HTTP check.
When no dependency service exists, that stage is reported as `not_required`.

## Usage

```sh
devops-agent validate /path/to/app
devops-agent validate /path/to/app --build
devops-agent validate /path/to/app --run --health-path /health
devops-agent validate /path/to/app --run --service web --container-port 3000 --timeout 300 --readiness-timeout 90 --json
devops-agent validate /path/to/app --run --keep-running
```

Build and runtime commands retain the first-release eligibility gate. The app
service is selected automatically only when exactly one service publishes ports;
its container port is selected only when exactly one TCP target exists.
The actual host port comes from Docker inspection, including ephemeral mappings.
The validator checks project/service labels and stable container IDs and port
bindings before and after a successful HTTP response. It preflights occupied
explicit host ports and never offers to stop an unrelated workload. The port
preflight is a point-in-time check, not an atomic reservation against host races.

HTTP probing disables proxies, uses HEAD with GET fallback on 405, and follows
at most five same-origin redirects. An external redirect, redirect loop, 401,
403, or non-2xx final response is not readiness. Choose an unauthenticated local
`--health-path` for apps whose home page requires login. HTTP and container checks
retry within the readiness deadline, allowing slow startup and healthchecks.

## Isolation and cleanup

Each invocation uses a unique Compose project. Builds receive unique image tags;
resolved Compose configuration is held in a temporary mode-0600 file and its
stdout is omitted from reports. Runtime requires a local Docker context.
Configurations with explicit/shared resource names, host namespaces, privileged
services, lifecycle hooks, or writable/external bind mounts are rejected before
build/start. Read-only regular-file mounts must be inside the selected app.
This intentionally supports a narrower set of Compose configurations than Docker.

A failed or cancelled start is cleaned up even if `up` created only some resources.
Cleanup runs scoped Compose `down --volumes`, verifies no containers remain with
the run's project label, and removes the run's build image tags. It does not prune
shared Docker caches. Cleanup failure makes the overall result fail and reports
an unknown environment state, even if HTTP readiness succeeded.

`--keep-running` preserves only a successful environment. The output gives its
project-specific stop command. Run that command while the original Compose file
still exists and resolves; preserved build image tags may be removed separately
after stopping. Failure and cancellation still attempt cleanup.

The default execution deadline is 300 seconds; readiness gets at most 90 seconds
within it. Commands have shorter per-stage caps where appropriate. Timeout or
Ctrl-C terminates the command process group. Cleanup gets a separate bounded
budget: up to 10 seconds for failure logs, 15 for shutdown, 10 for container
inventory, and 10 per run-owned image tag. An unavailable daemon can prevent
cleanup; use the reported project label to inspect leftovers after recovery.

## Evidence and limits

JSON includes stages, verified/unverified claims, command outcomes, inspected
service states, container-linked HTTP evidence, cleanup results, and the final
environment state. Host/executable, Docker engine/storage, build, startup,
service, HTTP, and cleanup failures remain distinct. Dependencies' observed
state and health appear in `dependency_checks` after successful readiness.
No build definitions produces `not_required`, not a claim that an image built.

The offline suite has 82 passing checks and no expected failures. An opt-in real
Docker smoke test also passed using cached Node 22, covering healthy startup,
redirects, healthchecks, conflict isolation, deliberate process exit,
authentication failure, and resource cleanup. See [test instructions](../tests/README.md).

This is a point-in-time local readiness result. It does not establish business
correctness, future uptime, full dependency behavior, or production readiness.
The lightweight smoke test does not install npm packages or build Next.js. A
separate step-7 generated Next.js acceptance run now passes image build, startup,
HTTP page-marker verification, and cleanup; historical storage-blocked evidence
remains unchanged. This is the pinned minimal development fixture, not a
production `next build` or broad framework certification.
Step 7 adds private action journals, stricter scope checks and report redaction;
see [execution safeguards](execution-safety.md) for coverage and limits.
