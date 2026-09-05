# Step 2: reproducible starting baseline

Recorded 2026-09-05 against agent commit
`3430f695a0d206bb51ae8c46a9e2f90ae7e14bea`. No production files in `agent/` were
changed for this step. This baseline measures a subset of the
[first-release contract](product-scope.md); it is not a support certification.

## Checkpoint decision

The previously uncommitted validation/context/diagnostic work was retained in
`c99a8f0`, and the scope documentation was committed in `3430f69`. Both were
already on `origin/main` at the start of step 2. Those commits form the baseline;
there was no remaining uncommitted product work to select or merge.

The new fixtures exercise that implementation as-is. Known bugs are recorded,
not silently fixed as part of establishing the starting point.

## Environment and reproducibility

| Item | Recorded value / implication |
| --- | --- |
| Host | macOS, arm64; exact platform string in offline evidence |
| System Python | 3.9.6, below the project's 3.10 minimum |
| Selected Python | 3.12.14 in a repository-local virtual environment |
| CLI dependencies | Typer 0.27.2, Rich 15.0.0, Requests 2.34.2; transitive versions in `requirements-baseline.txt` |
| Installation | Editable install succeeded; pip warns that this Typer version has no `all` extra |
| Docker | Client/engine 29.7.2; Docker Desktop 4.89.0; linux/arm64 engine |
| Compose | 5.5.0; different from the v2 target, so v2 compatibility remains unverified |
| Host port 3000 | Already occupied; existing workload was not intentionally stopped or reconfigured |
| Fixture packages | Next.js 16.3.4, React/React DOM 19.2.8; PostgreSQL client `pg` 8.23.0 |
| Lock generation | npm 10.9.8 in Node 22; real dependency graphs and integrity hashes checked in |
| Runtime execution limit | Host space fell below 300 MiB; reporting raised `OSError: [Errno 28] No space left on device` |

See [the test runbook](../tests/README.md) for setup and exact rerun commands.
Fixtures are materialized into new temporary directories. Test output and virtual
environments are ignored. Evidence records test/fixture hashes so changes to the
inputs can be distinguished from changes to the agent.

## Measured results

**22 checks: 14 pass, 8 expected acceptance gaps, zero unexpected failures or
skips.** Passing the baseline runner means these outcomes are reproducible; the
release is still not ready.

Passing behavior includes real CLI analysis without mutation, preserving an
existing setup, refusing an unknown Go stack, detecting PostgreSQL, lockfile
integrity, local HTTP status handling and HEAD-to-GET fallback, and simulated
Docker failure/declined-conflict handling. Docker responses are simulated only
in `FailureBaseline`; repository CLI and loopback HTTP checks are real.

| Gap | Scenario | Actual observation | Follow-up |
| --- | --- | --- | --- |
| G01 | S1/S3 | Generation requires `.env` even when the application has no variables. Real `validate` exits 1 during Compose configuration. | Step 4: generate environment configuration only when required. |
| G02 | S3 | Existing-setup detection exits 0 without identifying required APP_GREETING. | Steps 3–4: identify and validate required configuration. |
| G03 | S6 | Database-backed app receives generated setup and exit 0 despite being outside the first release scope. | Step 3: enforce service eligibility. |
| G04 | S6 | Node 18-only application receives Node 22 setup and exit 0. | Step 3: honor declared runtime requirements. |
| G05 | S6 | Missing npm lockfile does not block generation. | Steps 3–4: enforce and preserve dependency prerequisites. |
| G06 | S6 | Explicit yarn project receives npm setup and exit 0. | Step 3: identify package manager and enforce scope. |
| G07 | S7 | Two app components receive root Compose configuration without a root Dockerfile and exit 0. | Step 3: require application selection. |
| G08 | S8 | Dockerfile without Compose is reported as an existing setup with exit 0. | Steps 3–4: distinguish complete and partial setup. |

All gap checks assert the desired behavior and currently fail as expected.
Unexpected passes require updating the marker and this inventory; test errors
cannot be counted as known acceptance gaps by the canonical runner.

## Docker evidence and environment blocker

Before the runtime attempt, real production CLI calls established:

- Minimal app: `dockerize` exits 0; `validate` exits 1 because generated Compose
  requires an absent `.env`. Its diagnosis falls back to unknown failure.
- Existing complete setup: configuration-only `validate` exits 0 and preserves
  the fixture. This proves configuration parsing, not runtime readiness.

The first build attempt was blocked by write access to Buildx bookkeeping under
the user's Docker directory. The runner was updated to keep its Buildx metadata
in the temporary run directory. A subsequent attempt encountered host storage
exhaustion and could not save a new runtime report. The earlier report remains
separate evidence; no build, healthy-app, failing-app, or conflict runtime result
is inferred from it.

Docker subsequently returned server errors and a scoped cleanup attempt timed
out. No broad prune or Docker restart was performed, and cleanup of newly pulled
image/build cache could not be verified. The initial runner project was cleaned
up successfully as recorded in configuration evidence. State from the later
attempt cannot be certified while the engine is unresponsive.

The final runner now stops before Docker work if host free space is below 4 GiB
and writes evidence atomically so a failed write cannot truncate an older report.
The recorded final preflight is blocked. This minimum-space guard does not
guarantee sufficient capacity for every image build.

S1/S2 full `validate --run` remains untested on a free port-3000 environment.
S3/S4 runtime fixture behavior and a real fixture-owned S5 conflict also remain
unverified. Database startup, Compose v2, and additional architectures are not
certified. These are coverage limitations, not passing results.

## Evidence

- [Offline checks, failures, environment and fixture hashes](baseline/offline.json)
- [Actual Compose configuration calls and first build blocker](baseline/docker-config.json)
- [Final storage preflight blocker](baseline/docker-runtime.json)

Historical snapshots should be replaced only through an explicit baseline review.
Write fresh runs under `work/baseline/` and compare them to these snapshots.

## Next work

Step 3 can use G02–G08 as concrete acceptance cases for evidence-backed repository
understanding and eligibility. G01 is a generation prerequisite bug for step 4.
Runtime certification needs restored Docker/host capacity and the isolated
Docker runner first, followed by the actual CLI on an available port 3000.
