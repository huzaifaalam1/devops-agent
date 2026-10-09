# V2 step 6: Django development Docker setup

Complete for the bounded single-app Django/pip workflow with disposable SQLite.
The CLI and conversational agent use the same reviewed proposal, apply and runtime
validation tools as Next.js. Existing Next.js behavior remains covered by tests.

## Use

Select the app folder containing manage.py, requirements.txt, a declared Python
version and inspectable settings. In chat, ask:

> Set up this Django app with Docker, verify its unauthenticated page, and keep it running. Do not run migrations.

Review the generated diff, then approve build/run. To stop a retained environment,
ask `stop the app`. The default port is **127.0.0.1:8000**. A successful validation
without `keep_running` cleans up after checking; it does not leave a service running.

CLI equivalents:

```sh
devops-agent analyze /path/to/app
devops-agent dockerize /path/to/app --json
devops-agent dockerize /path/to/app --apply --expect REVIEWED_ID
devops-agent validate /path/to/app --run --keep-running
```

Use `--health-path /your-unauthenticated-path` when `/` is not a readiness endpoint.
An existing setup requires `--existing-setup --compose-file FILE` when using that
mode. Existing files are preserved; partial/ambiguous Docker setups require review.
Generated files must also pass the existing dirty-target and stale-proposal checks.

## What is generated

- Dockerfile using the repository's selected Python version with the slim image,
  pip installation from requirements.txt (including supported local includes),
  explicit DJANGO_SETTINGS_MODULE and `runserver 0.0.0.0:8000 --noreload`.
- Compose binding to loopback port 8000, with no host database or source mounts.
  A regular, unlinked `.env`, if present, is passed at runtime. The selected settings
  module is explicit and overrides a conflicting dotenv declaration. No secret
  values are embedded in the generated files.
- Appended build exclusions for dotenv files, host Python caches/environments and
  SQLite database files/sidecars. Existing ignore rules are preserved before them.

A default SQLite `:memory:` database or a simple `.sqlite3` / `.db` filename is
supported, including `BASE_DIR / 'db.sqlite3'`. Dynamic, shared, absolute, nested,
or multiple-database configurations are blocked. Generated builds exclude host
SQLite files; resulting container storage is disposable. Stop preserves that
container's data; removing it discards that data. No migrations are run.

This is development support, not production deployment. Install failures, missing
runtime configuration, auth-only pages, pending migrations and failed readiness
checks remain actual failures—not claimed success. Python/settings ambiguity and
unsupported dependencies remain blockers. PostgreSQL initialization and migrations
are step 7; no existing databases are modified automatically.

## Verification

**302 offline tests passed** with no skips or expected failures. Tests include
Python templates, environment exclusion, stale settings/included requirements,
existing/partial setup preservation, Postgres refusal before Docker dispatch,
SQLite path restrictions, linked dotenv refusal, and existing Next.js regressions.

The final live test used Groq and a fresh copy of the Django fixture with a host
SQLite marker table and runtime-only environment value. The test harness approved
only generated-file apply and runtime verification actions. It paused/restarted
at apply approval, then obtained a fresh review. The final run verified:

- Model proposal → reviewed apply → generated Docker build → owned HTTP 200 with
  the expected body → kept-running state → reviewed stop.
- The image lacked `.env` and the host-only SQLite table; the runtime environment
  value was available, and the selected settings module was used.
- The host database hash stayed unchanged. Owned containers, network and generated
  image were removed after testing; unrelated running containers were preserved.

The final run used four model requests. Its first runtime action set existing_setup
without a Compose filename; deterministic selection refused it before execution.
The model supplied the filename on its next reviewed action and succeeded. This
is retained as a recovered mistake, not a perfect first-attempt claim.

An earlier run reached startup/stop but its test-harness cleanup used a noncanonical
macOS temporary path and failed. It did not save complete check results, so it is
not counted as a full pass. Its exact owned container, network and image were
removed separately. The harness now resolves the path and saves results before
cleanup. Reports and logs retain both attempts. Final source hashes match the
final offline and live reports.

Reproduce offline: `python -m tests.run_baseline`. Opt-in real acceptance:
`python -m tests.django_step6_smoke` (Groq configuration, Docker Desktop, network,
free port 8000 and 8 GiB free disk). This creates only disposable test resources.
The frozen fixture proves this path; it does not certify every Django repository
or the earlier multi-app Django/Vue pilot.

Next: step 7, disposable PostgreSQL and explicitly approved migrations.
