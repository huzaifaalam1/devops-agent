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

It does not call production `validate --run`: that command assumes host port
3000, which was already occupied. Successful controlled runtime checks would
therefore be component evidence, not end-to-end release acceptance. The HTTP
check also looks for a fixture-specific page marker to avoid treating another
server as the app.

Builds and commands have external time limits. Cleanup covers attempted starts
and the runner-owned image; it never prunes shared Docker state or stops another
project. Pulled base images and BuildKit cache may remain. A daemon/storage
failure can prevent cleanup, and is reported as an error. Restore engine health
and inspect the recorded runner project names before retrying.

The recorded runtime attempt hit host storage exhaustion. Final preflight reports
less than 4 GiB free and skips execution. Runtime fixtures are present but have
not been verified end to end; no green Docker runtime result is recorded.
