# First release: local startup for one stack

Status: scope decision for implementation; runtime acceptance is not yet verified.

## User and job

The first user is a developer onboarding to an unfamiliar repository on a Mac
with Docker Desktop installed. They want to discover prerequisites, prepare a
local development environment, and establish whether the app actually works
without manually interpreting every configuration file and startup log.

The product promise is: **take an eligible checkout to a verified running local
application, or explain the specific blocker and next action with evidence.**

## Initial stack decision

Start with one Next.js application, managed by npm, in the directory supplied
to the command. Require `package.json`, `package-lock.json`, a `next` dependency,
and an explicit `dev` script that starts the app. The app must be compatible
with the generator's Node 22 image; declared incompatible runtime requirements
must become a blocker rather than being silently ignored.

This choice minimizes the gap to the existing Node/Next.js template, which uses
`npm run dev` and port 3000. It is a planning assumption based on this codebase,
not evidence that Next.js is the user's most common stack. Revisit the choice
when the representative repository set is assembled in step 2.

Initial environment boundaries:

- macOS host, working Docker Desktop engine, and Docker Compose v2.
- One application with an unauthenticated local HTTP readiness endpoint.
- Default host port 3000; alternative ports are outside the first release target.
- No required database, worker, cloud service, or private package registry.
- Explicitly documented environment variables supplied locally by the user.
- A checkout the developer is authorized to execute, with prerequisites and
  network access for dependency and image downloads available.
- Dependency versions must be captured by the lockfile. Actual version
  combinations and machine architecture coverage will be recorded in the
  step-2 baseline; this document does not certify a version range.

Database-backed apps are valuable expansion cases, but adding a database
container alone does not establish application connectivity or readiness.

## Capability matrix

"Experimental" means a code path exists, not that its correctness was measured.
"Target" means required for the first reliable release. Existing capabilities
outside that target can remain available without being advertised as supported.

| Scenario | Identify today | Generate today | Validate today | Diagnose / repair today | First release commitment |
| --- | --- | --- | --- | --- | --- |
| Single Next.js app, npm | Experimental dependency-text detection | Experimental Node template | Generic Compose checks and port-3000 HTTP probe | Generic error rules; no general repair | Target: evidence-backed analysis, correct setup, verified readiness, actionable failure |
| Other Node apps / Vue | Experimental | Generic Node template assumes `npm run dev` | Same generic checks | Generic error rules | Best-effort analysis; no startup guarantee |
| Django / generic Python | Experimental | Django-style template assumes `requirements.txt` and `manage.py` | HTTP probe still assumes port 3000, while template exposes 8000 | Generic error rules | Best-effort analysis; no startup guarantee |
| Flask / FastAPI | Experimental requirements-text detection | No dedicated template; may select a Django template if classified as generic Python | Generic checks only | Generic error rules | Best-effort analysis; generation outside scope |
| Rails / Ruby | Experimental Gemfile detection | Rails-style template | Generic Compose and HTTP checks | Includes missing-gem diagnosis | Best-effort analysis; no startup guarantee |
| Multiple application components | Experimental directory discovery | No coordinated component setup | Generic checks only | Generic error rules | Identify ambiguity and request the app directory |
| PostgreSQL, MariaDB, MongoDB, Redis, Sidekiq | Experimental dependency detection | Service stanzas exist | Container checks do not prove dependency readiness | Limited connection-failure rules | Dependency-backed startup deferred |
| Existing Docker configuration | File-name discovery | CLI skips generation if either Dockerfile or Compose exists | Experimental Compose validation | Can offer to stop a conflicting Compose project and retry | Reuse eligible complete setup; report partial or incompatible setup without overwriting |
| Unknown stack | Unknown-stack result | CLI refuses a fully unknown stack | Existing Compose may still be checked | Generic error rules | Explain unsupported scope; do not generate misleading setup |

Source of current-capability claims: `agent/scanner.py`, `agent/detector.py`,
`agent/docker_generator.py`, `agent/validator.py`, `agent/diagnostics.py`, and
the command wiring in `agent/main.py`. This is a code inventory, not a test report.

## Supported scenarios and expected outcomes

The behaviors below are acceptance requirements for the release. They are not
all enforced by the current CLI.

| ID | Trigger | Expected outcome |
| --- | --- | --- |
| S1 | Eligible app without Docker files | Explain detected prerequisites, propose matching setup, preserve the lockfile's dependency intent, and verify the app after applying approved changes. |
| S2 | Eligible app with complete compatible Compose setup | Reuse it, identify the selected Compose file, and verify readiness without replacing existing files. |
| S3 | Required environment values are missing | Identify variable names and where they are required; stop before startup rather than invent values or print secrets. An app requiring no variables must not fail solely because `.env` is absent. |
| S4 | Docker unavailable, build fails, or app fails readiness | Report the failing stage, relevant evidence, and a concrete next action; return failure. |
| S5 | Port 3000 occupied by another workload | Identify the conflict and report a blocker; never stop an unrelated workload without explicit authorization. |
| S6 | Unsupported stack, runtime, package manager, or required service | Explain which scope constraint failed; offer best-effort analysis and an actionable next step, with no generated setup or verified-support claim. |
| S7 | Multiple app directories or conflicting project evidence | Explain the ambiguity and request the intended directory or missing information before generation. |
| S8 | Partial or incompatible Docker setup | Report missing or conflicting configuration and the next action; do not treat “setup already exists” as proof the app can run. |

## Definition of verified success

For S1 and S2, all of the following must hold:

1. Evidence identifies an eligible project, its startup command, runtime,
   required environment variable names, and selected Compose configuration.
2. Compose configuration validates and required images build successfully.
3. Expected long-running services remain running throughout the readiness check;
   any declared health checks pass. Failed commands cannot be ignored.
4. The intended app's readiness endpoint returns a successful 2xx response within
   a bounded readiness period. Evidence must tie the endpoint to this Compose
   application; an unrelated server on the same port cannot establish success.
5. The result records the URL, HTTP status, service results, and any unverified
   conditions. Configuration-only and build-only success are labeled separately
   from application readiness.
6. With `--keep-running`, the verified app remains running and its address is
   reported. Otherwise, the result states that verification completed and the
   environment was stopped. Cleanup affects only resources owned by the run.

Until these criteria pass on the representative projects, documentation and CLI
messaging must describe support as experimental. Readiness proves local startup,
not business correctness, production readiness, or security certification.

## Explicit exclusions

- Production deployment, AWS provisioning, Kubernetes, Terraform, and remote hosts.
- Automatic CI/CD creation or infrastructure administration.
- Monorepo orchestration, yarn/pnpm support, and arbitrary framework generation.
- Database provisioning/migrations, background workers, and required cloud services.
- Authentication-dependent readiness, HTTPS/custom-domain setup, and alternative ports.
- Automatic application-code repair or unrestricted shell execution by a model.
- Destructive actions, modifying unrelated workloads, or silently overwriting work.

## Step-1 completion and implementation handoff

Step 1 is complete when the product user, initial stack, support matrix, scenario
outcomes, exclusions, and success criteria are written down and internally
consistent. It does not require implementing later roadmap steps.

Before claiming this first release is supported, subsequent work must:

- Step 2: build representative fixtures for S1–S8 and record baseline outcomes.
- Step 3: enforce eligibility and distinguish facts, unknowns, and unsupported cases.
- Step 4: preview matching setup and handle lockfiles, environment prerequisites,
  and existing files correctly.
- Step 5: remove readiness assumptions, verify endpoint ownership, and bound
  execution and cleanup.
- Steps 6–7: provide evidence-backed diagnostics and scoped, recoverable execution.

General autonomous repair and model-driven reasoning remain later release gates.
