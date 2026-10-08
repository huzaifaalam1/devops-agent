# DevOps Agent

A bounded local development assistant for **single-app Next.js projects using
npm**, on macOS with Docker Desktop. Inspect a repository, review Docker setup,
run it in isolation, and get evidence of readiness or a concrete blocker.

v1 uses deterministic rules for execution. Optional model explanations do not
execute commands. It does not automatically fix arbitrary application code or
support every repository. See the [support contract](docs/product-scope.md) and
[v1 verification record](docs/releases/v1.md).

## Install

From this repository, with Python 3.10+ (Python 3.12 is the tested environment):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements-baseline.txt -e .
source .venv/bin/activate
docker version
docker compose version
```

Start Docker Desktop if the server is unavailable. Installation and builds need
network access; real acceptance tests require at least 8 GiB free host storage.

## Run a supported app

Supply the application directory, not its parent monorepo. It needs a matching
npm lockfile, an explicit Node engine requirement, and a supported `next dev`
script. Resolve analysis blockers before generation.

```sh
devops-agent analyze /path/to/app
devops-agent dockerize /path/to/app --json
# Review the proposed changes and copy their ID:
devops-agent dockerize /path/to/app --apply --expect REVIEWED_ID
devops-agent validate /path/to/app --run --keep-running
```

Success prints the owned URL and a scoped stop command. Run that stop command
when finished. Omit `--keep-running` to verify and clean up immediately: the app
will no longer be running after the command returns. `validate` alone checks
configuration; `--build` checks the build; only `--run` tests readiness.

Existing setups are preserved. Select among Compose variants explicitly:

```sh
devops-agent validate /path/to/app --existing-setup \
  --compose-file compose.dev.yaml --run --keep-running
```

This mode still enforces isolation and supported framework checks. It does not
rewrite unsafe/shared configurations or initialize databases for you. Service
health and HTTP readiness do not prove database business operations.

## Configuration and troubleshooting

No model key is needed to analyze, generate, validate or use bounded repairs.
Place **application** variables in the app's documented local dotenv files.
Review [environment handling](docs/docker-proposals.md) before using secrets;
never commit them. Missing example values are uncertain requirements, not proof
that every variable is mandatory.

For optional advice, copy `.env.example` to `.env` in the **agent repository**
only if `.env` does not already exist. Paste `GROQ_API_KEY` there. Groq is the
default provider; no automatic paid fallback is enabled. Rate limits still apply.
Preview sanitized evidence before authorizing a request:

```sh
devops-agent advise /path/to/app --json
devops-agent advise /path/to/app --send --expect REVIEWED_ID --json
```

Use `validate ... --json` for structured results or `--verbose` for redacted
captured logs. `--health-path`, `--service` and `--container-port` select a probe;
`--timeout` and `--readiness-timeout` bound execution. On a port conflict, change
only this project's binding or use the [bounded repair](docs/bounded-repair.md).
Do not stop the port owner. See [troubleshooting](docs/troubleshooting.md).

`history` lists private action records; `recover PATH SESSION_ID` previews guarded
recovery and `--apply` authorizes restoration. See [execution safeguards](docs/execution-safety.md).

## Verification and limits

Three external repositories passed assisted runtime checks, with manual setup
recorded for each. This is not a claim of autonomous support for arbitrary repos.
The [v1 record](docs/releases/v1.md) links the final offline suite, fresh generated
workflow, pilot evidence, and remaining limitations. Optional model quality is
only provisionally reviewed; see [model evaluation](docs/evaluations/step9-v8/review.md).

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m tests.run_baseline --output work/offline.json
# Opt-in real build; choose a free host port on shared development machines:
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m tests.docker_nextjs_acceptance \
  --host-port 43187 --output work/runtime.json
```

The runtime runner uses a fresh pinned fixture and verifies its page content and
scoped cleanup. A nondefault host port is recorded as an explicit test adjustment.
Shared base images and build cache remain. Detailed workflows:
[Docker proposals](docs/docker-proposals.md), [runtime validation](docs/runtime-validation.md),
[test guide](tests/README.md), [model configuration](docs/model-planning.md).

## V2 roadmap

The [v2 scope and ten-step plan](docs/v2/plan.md) and
[acceptance matrix](docs/v2/acceptance.md) define the next release: an interactive
terminal agent, Django/Postgres support, and reviewable AWS preparation.
Steps 1–2 provide the plan and read-only terminal shell; execution support remains v1.

V2 step 2 adds a read-only interactive preview:

```sh
devops-agent chat /path/to/app
```

Omit the path to be prompted. Ask to inspect the repo or explain blockers; use
`/status`, `/cancel`, `/repo PATH` and `/exit`. Setup requests explain next steps
but do not execute yet. No model key is needed. See the
[terminal preview guide](docs/v2/terminal.md).
