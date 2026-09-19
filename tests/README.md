# Baseline fixtures and checks

Run commands from the repository root. Product implementation stays in `agent/`;
these files exercise it without changing its behavior.

## Prerequisites and installation

- Python 3.10 or later; recorded interpreter: 3.12.14. The host's default
  `/usr/bin/python3` is 3.9.6 and cannot run this project. Select a compatible
  interpreter explicitly; `python3.12` below is an example executable name.
- Install the package and the dependency versions captured in
  `requirements-baseline.txt`. These are baseline constraints, not a replacement
  for `poetry.lock` or a new production dependency policy.
- The offline suite uses `unittest`, real CLI subprocesses, temporary files, and
  a loopback HTTP server. It needs neither npm nor Docker, and makes no external
  HTTP requests. Python package installation itself needs package index access.
- The optional Docker runner needs a working engine and the `docker compose`
  plugin, access to Docker Hub/npm, and at least 4 GiB of free host space.
  This is a minimum guard, not a guarantee that every build fits. The available
  plugin was Compose 5.5.0; the step-1 Compose v2 target is not yet certified.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -c requirements-baseline.txt -e .
.venv/bin/python -m tests.run_baseline --output work/baseline/offline.json
```

The existing repository tracks some `devops_agent.egg-info` files despite ignoring
that directory. Editable installation can rewrite those generated files. This is
existing packaging debt; inspect such diffs separately from product changes.

## Reading results

The canonical runner is `tests.run_baseline`; it discovers all `tests/test_*.py` suites,
including evidence/eligibility checks in `test_understanding.py` and proposal
checks in `test_proposals.py`. It reports passes, expected
acceptance gaps, unexpected failures, unexpected successes, and skips separately.

- A passing check protects existing useful behavior.
- An expected failure is an assertion against the desired product behavior,
  linked to the historical G01–G08 inventory. After step 4, G01–G08 are all ordinary passing regression checks; no expected
  failures remain. It is **not** an assertion that a
  bug should remain. When fixed, remove its `expectedFailure` marker.
- An unexpected success exits nonzero so an improvement triggers review of the
  old gap classification.
- Crashes and timeouts inside known-gap checks are errors, not expected failures.
- `baseline_matches: true` means the observed checks match the recorded baseline.
  `release_ready` stays false because this suite alone cannot prove Docker
  acceptance or the entire release contract.

Evidence includes the tested agent commit, any tracked agent diff, interpreter
and library versions, assertions for known gaps, and hashes of fixture/test files.
The checked-in evidence under `docs/baseline/` is historical. New runs go to
ignored `work/`; do not overwrite historical results merely to make a check pass.

## Fixture catalog

`fixtures/cases.json` maps all twelve cases to S1–S8 and their target outcomes.
`fixture_support.py` copies a common app and overlays into a fresh destination.
It refuses to overwrite an existing directory. Tests operate only on temporary
copies, never on the checked-in fixtures or user repositories.

| Case | Scenario | Distinguishing condition |
| --- | --- | --- |
| minimal | S1 | Real Next.js app, no Docker files and no environment requirements |
| existing-compose | S2 | Complete Dockerfile/Compose setup using `npm ci` |
| missing-env | S3 | Next config throws until APP_GREETING is provided |
| startup-failure | S4 | Next config deliberately throws on startup |
| port-conflict | S5 | Existing Compose setup; conflict injected at the external boundary |
| unsupported | S6 | Go source and module metadata |
| database | S6 | Real `pg` dependency and a server-rendered page querying PostgreSQL |
| incompatible-runtime | S6 | Node 18-only engine declaration in package and lock metadata |
| missing-lockfile | S6 | Valid package manifest with npm lockfile removed |
| yarn | S6 | Explicit yarn packageManager; no npm lockfile; no generated yarn lockfile |
| multi-component | S7 | Two independent Next.js apps, with no root application |
| partial-docker | S8 | Dockerfile exists, Compose does not |

The database case is an out-of-scope analysis/generation fixture, not a claim of
verified database-backed startup. The yarn case tests explicit package-manager
identification, not yarn installation.

The app layout follows the [official Next.js installation structure](https://nextjs.org/docs/app/getting-started/installation).
Fixture dependencies are pinned to Next.js 16.3.4, React/React DOM 19.2.8, and
`pg` 8.23.0 for the database overlay. Both npm lockfiles were generated with npm
10.9.8 in Node 22 and include resolved package versions and integrity hashes.
The existing Dockerfile also pins its Node image digest. These are the fixture's
specific versions, not a framework compatibility certification.

To inspect a fixture manually:

```sh
.venv/bin/python -m tests.fixture_support minimal work/fixtures/minimal
.venv/bin/python -m agent.main analyze work/fixtures/minimal
.venv/bin/python -m agent.main dockerize work/fixtures/minimal
# Apply only after reviewing the preview:
.venv/bin/python -m agent.main dockerize work/fixtures/minimal --apply
```

Reruns must choose a fresh destination. Do not run `dockerize` inside
`tests/fixtures/` itself.

## Optional Docker evidence

```sh
.venv/bin/python -m tests.docker_baseline --output work/baseline/docker.json
```

The runner checks real generated Compose configuration and an existing Compose
configuration. It then attempts a pinned fixture image build and controlled
healthy, missing-variable, deliberate-failure, and port-conflict cases. It uses
unique Compose project/image names, temporary directories, and ephemeral ports
bound to loopback. It creates a port conflict only against its own fixture.

This historical runner does not call production `validate --run`: at the
step-2 checkpoint that command assumed host port 3000, which was already occupied. Successful controlled runtime checks would
therefore be component evidence, not end-to-end release acceptance. The HTTP
check also looks for a fixture-specific page marker to avoid treating another
server as the app.

Builds and commands have external time limits. Cleanup covers attempted starts
and the runner-owned image; it never prunes shared Docker state or stops another
project. Pulled base images and BuildKit cache may remain. A daemon/storage
failure can prevent cleanup, and is reported as an error. Restore engine health
and inspect the recorded runner project names before retrying.

The recorded runtime attempt hit host storage exhaustion. Final preflight reports
less than 4 GiB free and skips execution. Those Next.js runtime fixtures have not been verified end to end; the historical
evidence remains unchanged.


## Step-5 validator smoke checks

`test_validation.py` exercises lifecycle failures, ownership, timeouts,
cancellation, health checks, and cleanup through explicit Docker boundary fakes.
The loopback HTTP tests cover redirects, redirect loops, authentication, and
HEAD-to-GET fallback. The complete offline suite has 82 passing checks.

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m tests.docker_validation_smoke --output work/step5-docker.json
```

This opt-in runner calls the production validator against real Docker using an
already-cached `node:22` image. It refuses to pull an absent image and performs
no image builds or npm installation. It verifies HTTP readiness, a same-origin
redirect, Docker healthchecks, an occupied port with its original owner still
healthy, a process exiting with code 42, HTTP 401 rejection, and scoped cleanup.
It intentionally keeps its healthy fixture running only until the conflict
check finishes; a `finally` block removes it and verifies no project containers
remain. Other fixture runs exercise the validator's own automatic cleanup.

This passed with Docker 29.7.2 / Compose 5.5.0. It is runtime-validator evidence,
not Next.js build acceptance or Compose v2 certification. Fresh evidence belongs
in ignored `work/`; historical `docs/baseline/` snapshots are not rewritten.


## Step-6 diagnostic checks

`test_diagnostics.py` tests supported failure categories, evidence provenance,
uncertainty and unknown outcomes, classification precedence, and CLI summary,
verbose, JSON, and missing-configuration preflight behavior. Run it through the
canonical baseline runner; the full suite now has 96 passing checks. These tests
use captured boundary fixtures and do not need Docker or install dependencies.
See [troubleshooting](../docs/troubleshooting.md) for the catalog and limits.


## Step-7 safety checks

`test_safety.py` covers explicit action categories, private journals, recovery,
subsequent-edit refusal, dirty Git targets, links, cancellation, concurrent agent
locks, audit failures, report redaction, and Docker execution scope. Test sessions
use private temporary journal storage by default; an explicit
`DEVOPS_AGENT_STATE_DIR` overrides it. The full suite has 118 passing checks.
The real Docker smoke retry passed against the step-7 implementation, including
readiness, conflict isolation, failure handling and cleanup. Evidence is in
ignored `work/step7-docker.json`; no Next.js build was performed. See
[execution safeguards](../docs/execution-safety.md).


## Generated Next.js acceptance

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m tests.docker_nextjs_acceptance --output work/step7-nextjs.json
```

This runner passed against the real Docker engine. It creates a disposable copy
of the minimal pinned Next.js fixture, uses CLI proposal/apply, and calls the
production validator to build and run the generated setup without altering its
loopback port 3000 mapping. It additionally fetches the response body and requires
`devops-agent-baseline-ready`, then verifies scoped container and image cleanup.
It requires port 3000 to be free and at least 8 GiB of host space, uses private
temporary Buildx/journal storage, and permits npm/image network downloads. Build
and readiness deadlines are 600 and 120 seconds. Shared base images and build
cache remain; no global pruning is performed. This is a development image/startup
check, not a production `next build`. The successful run retained about 24 GiB
of free host space. Historical baseline evidence is not overwritten.


## Step-8 bounded repair

The canonical runner includes `test_repair.py`; the full offline suite has 138
passing checks. It tests approval and input binding, successful repair, rollback,
cancellation, concurrent user edits, repeated-attempt refusal, scope exclusions,
CLI output and secret redaction. Loopback sockets reproduce port ownership;
Docker execution is replaced by explicit boundary fixtures in this suite.

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m tests.docker_repair_smoke --output work/step8-docker.json
```

The opt-in real runner exercises generated Next.js port repair and a supplied
unauthenticated `/health` path after an observed HTTP 401. It requires Docker,
8 GiB of free space, and image/npm download or cache access. Journals and Buildx
metadata use private temporary directories. Each validator run cleans its owned
resources, and the runner independently checks that no run containers remain.
See [bounded repair](../docs/bounded-repair.md) for usage, bounds and recovery.

The step-8 real Docker run passed both repair kinds and verified cleanup, with
evidence in `work/step8-docker.json`. The fixture waits for Docker Desktop to
release its own previous port before approving the readiness-path retry; this
pre-approval wait is separate from the single allowed repair attempt.
