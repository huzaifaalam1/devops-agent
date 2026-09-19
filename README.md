# DevOps Agent

A local command-line assistant for understanding a repository, preparing Docker
development setup, and diagnosing startup failures.

## First product promise

Help a developer run an unfamiliar, single-application **Next.js project using
npm** locally with Docker, and report evidence that the intended app is ready.
The initial target is macOS with Docker Desktop and Docker Compose v2.

This is the first release **target**, not a claim of verified support today.
The implementation is experimental, uses fixed rules and templates, and has no
model-driven planning or general autonomous repair loop. Framework detection
does not imply that generation or runtime validation works for that framework.

See the [product scope and acceptance criteria](docs/product-scope.md) for the
supported scenarios, capability matrix, exclusions, and definition of success.

## Current commands

After installing this package in a Python 3.10+ environment, the entry point is
`devops-agent`. Docker operations require an available Docker engine and Compose.

```sh
devops-agent analyze /path/to/app
devops-agent analyze /path/to/app --json
devops-agent dockerize /path/to/app
devops-agent dockerize /path/to/app --apply
devops-agent validate /path/to/app
devops-agent validate /path/to/app --build
devops-agent validate /path/to/app --run
devops-agent validate /path/to/app --run --keep-running
```

- `analyze` inspects files and reports detected stacks, services, and recommendations.
- `dockerize` previews file changes and their reasons. `--apply` writes the
  proposal; `--expect <proposal-id>` requires a previously reviewed version.
  See [Docker proposals](docs/docker-proposals.md) for environment handling and limits.
- `validate` checks Compose configuration; `--build` also builds images.
  Building and starting services require eligibility; configuration-only checks
  remain available for other stacks.
- `--run` builds and starts services and attempts an HTTP readiness check.
  It uses a unique validation project and removes it afterward; `--keep-running`
  preserves only a successful run and prints its scoped stop command. A successful check without `--keep-running` does not mean
  the application is still available after the command exits.

Runtime checks discover the published port from the validation containers.
Use `--service`, `--container-port`, and `--health-path` when selection is needed;
`--timeout` and `--readiness-timeout` bound execution. `--json` includes stage,
container, HTTP, cleanup, and unverified evidence. See
[runtime validation](docs/runtime-validation.md) for isolation requirements and limits.

Current limitations include conservative Next.js startup requirements. Review generated files before running them. The release criteria
in the scope document remain work to implement and verify.

Failed validation includes an evidence-backed diagnosis, recommended action,
expected impact, and verification instructions. Use `--verbose` for captured logs
or `--json` for structured details. See [troubleshooting](docs/troubleshooting.md).

Applied edits now have private recovery records; `history` lists actions and
`recover PATH SESSION_ID` previews guarded recovery (`--apply` restores it).
Reports are redacted, and runtime operations enforce project scope. See
[execution safeguards](docs/execution-safety.md) for approvals, storage, and limits.

A small [bounded repair workflow](docs/bounded-repair.md) can propose an available
host port for generated Compose files or retry a supplied readiness route.
`repair --apply --expect ID` authorizes one verification attempt; unsuccessful
file edits receive guarded rollback and repeated attempts are refused.

## Reproduce the baseline

The [step-2 baseline](docs/baseline.md) records the checkpoint, environment,
scenario results, known gaps, and Docker execution limits. Fixture sources and
repeatable commands are documented in [tests/README.md](tests/README.md).

Use a Python 3.10+ interpreter (the recorded run used Python 3.12.14):

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -c requirements-baseline.txt -e .
.venv/bin/python -m tests.run_baseline --output work/baseline/offline.json
```

The historical step-2 baseline has **14 passing checks and 8 known acceptance gaps**.
After [step 8](docs/bounded-repair.md), the expanded suite has **138 passing
checks and zero expected failures**; G01–G08 are now passing regression checks.
An expected failure documents missing product behavior; it is not a release
pass. Docker evidence is separately opt-in. The historical storage-blocked result
is preserved. Step 7 now also passes the real generated Next.js development
workflow: image build, startup, HTTP 200 with the fixture page marker, and cleanup.
This verifies the pinned minimal fixture, not production builds or every Next.js app.
