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
devops-agent dockerize /path/to/app
devops-agent validate /path/to/app
devops-agent validate /path/to/app --build
devops-agent validate /path/to/app --run
devops-agent validate /path/to/app --run --keep-running
```

- `analyze` inspects files and reports detected stacks, services, and recommendations.
- `dockerize` writes missing setup files when no Dockerfile or Compose file was
  detected. It currently has no preview or support-policy enforcement.
- `validate` checks Compose configuration; `--build` also builds images.
- `--run` builds and starts services and attempts an HTTP readiness check.
  It normally brings the Compose project down afterward; `--keep-running`
  leaves it running. A successful check without `--keep-running` does not mean
  the application is still available after the command exits.

Current limitations include a fixed port 3000 for application validation,
generated Compose files requiring `.env`, and framework-specific startup
assumptions. Review generated files before running them. The release criteria
in the scope document remain work to implement and verify.

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

The baseline currently has **14 passing checks and 8 known acceptance gaps**.
An expected failure documents missing product behavior; it is not a release
pass. Docker build/runtime evidence is separately opt-in and was blocked by
host storage during this baseline. No end-to-end startup support is certified.
