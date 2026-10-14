# Step 7 — disposable Django/PostgreSQL

The conversational workflow has three independent reviews:

1. `apply_docker` applies the displayed development files.
2. `prepare_database` builds a new app image, starts a new PostgreSQL 16 container,
   waits for PostgreSQL health, checks the effective Django connection, and reads
   the forward migration plan. The app waits instead of serving requests.
3. `migrate_database {session_id}` applies the reviewed plan, checks Django ORM
   create/read/delete using a diagnostic table, removes that table, starts Django,
   and checks the owned loopback HTTP endpoint.

Preparation is **not application readiness**. Its report explicitly leaves
migrations and HTTP unverified. Migration approval shows exact session/container
IDs, pending migration names and operation types. The executor checks the plan,
applied migration history and Python source digest again before applying it.
Django's built-in migrate command supplies its normal migration signals; no
migration files are generated and no model-supplied management command runs.

## Supported inputs and lifecycle

This extends the step-6 Python/Django/pinned-pip contract. PostgreSQL settings must
have one `default` dictionary with `ENGINE='django.db.backends.postgresql'` and
five distinct direct `os.environ[...]`, `os.environ.get(...)` or `os.getenv(...)`
references for `NAME`, `USER`, `PASSWORD`, `HOST` and `PORT`. The environment names
are inferred, not hardcoded. Runtime values are replaced with the fresh disposable
target. A compatible PostgreSQL driver must already be declared in requirements.
Literal/external targets, extra database options, multiple aliases and routers
are refused. Existing Compose/Dockerfiles are not automatically rewritten or
adopted; preparation requires the exact generated files and build exclusions.
Dockerfile-specific ignore overrides are refused.

The generated setup uses loopback application port 8000, an app-only ingress network and an internal project-owned database network, no database host
port, and PostgreSQL tmpfs storage. Preparation generates a fresh random password
in memory and stages it only in the private temporary Compose configuration and
Docker's container environment. It is not written to repository files or reports.
Docker administrators can inspect container environments; this is local
isolation, not a sandbox against a hostile host. A supplied `.env` stays out of
the image and supplies other runtime settings. The template password is a
placeholder; use the agent preparation workflow for generated runtime credentials.

**Stopping the database destroys its data.** Containers/networks/images remain
available after `stop_runtime`; tmpfs contents do not. There is no persistence,
resume-after-stop or production database promise. Each new preparation is a new
empty database. The test harness removes only its exact owned containers,
project-labeled networks and generated app image.

Planning executes repository Python inside the reviewed app container, with
PostgreSQL transactions defaulting to read-only. Repository code remains code:
this is not a security sandbox for hostile Python or migration operations.
Before connecting, effective settings must match the disposable contract; after
connecting, server IP/database/user must match the owned database. Both migrations and app startup pin the ownership-checked database container IP rather than depending on Docker DNS. Source,
container, network or plan changes refuse execution. A private persistent fence
is written before attempting migrations. Failed/interrupted/completed attempts
cannot be replayed through a fresh chat. No reset, reverse migration, automatic
rollback or adoption of an existing database is provided. On a failed attempt,
inspect and stop the owned environment, then prepare a fresh one.

The generic ORM probe proves connectivity and basic database writes, not every
business operation. The acceptance fixture additionally serves a page that
creates, reads and deletes its own migrated `Note` model. Real application health
currently uses the unauthenticated `/` route on container port 8000; other topologies and
custom readiness paths remain outside this first PostgreSQL workflow.

## Verification

Offline tests: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -q`.
Opt-in Docker acceptance: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m tests.django_step7_smoke`.
Add `--live` for actual Groq action selection, with trusted harness approvals and
35-second pacing between decisions. A 429 terminates that attempt; there is no
automatic retry. Model success is not established by the deterministic run.

The 314-test offline suite and the real Docker workflow on port 8000 passed; see
[offline evidence](offline.json) and [Docker evidence](docker-8000.json). Earlier
failed development attempts are summarized in [attempts](attempts.json), with raw
reports retained under ignored `work/v2-step7/`. They are not counted as passes.
Port 8000 is the default: if occupied, ask the user to make it available rather
than stopping their service or silently changing the port.

The fresh live-agent result is recorded separately below. Step 8 still owns the
broader frozen held-out model-quality evaluation; this fixture is integration
evidence, not proof of general repository support.

Implementation references: [Django migrate command](https://docs.djangoproject.com/en/5.2/ref/django-admin/#migrate)
and [official PostgreSQL image](https://hub.docker.com/_/postgres).

The [live Groq run](live-8000.json) passed with 4 model requests and three separate mutation reviews (apply, prepare, migrate), followed by a reviewed stop. Both real runs checked application-model create/read/delete through HTTP 200 on `http://127.0.0.1:8000/`, refused migration replay, cleaned up their resources and preserved pre-existing running containers. See [the manifest](manifest.json) for versions, source hashes and the subsequent proposal-hint-only correction.

Earlier live attempts stopped on a 429 and on the planner asking for permission in prose instead of opening the tool review. The final prompt opens that review through tool selection. Development Docker failures exposed connection address normalization, tmpfs inspection, service snapshot typing and the need for an app-only ingress network; those failures are retained and are not counted as successful evaluations.
