# Assisted Next.js/Postgres pilot

Upstream: `nextjs-docker-postgres-template`, commit
`1b41f5b4aee4ef19621f2141feee0412b56614e6`. Original checkout is unchanged.

Manual setup in an ignored copy:
- Select the upstream Dockerfile's `dev` target, preserving Node 20 and npm ci.
- Replace fixed container names, source bind mounts and fixed host ports with an
  isolated Compose project and one dynamically allocated loopback app port.
- Use a disposable database password stored only in a private ignored `.env`.
- Run local Prisma generation and schema push before the upstream dev command;
  the upstream README requires these initialization steps.
- Use temporary in-memory Postgres data, with a health check. The first attempt
  using a named volume was refused by the existing isolation policy.

Initial runtime attempt used the validator directly to diagnose requirements;
this did not demonstrate that the CLI eligibility path worked. Postgres became
healthy, but Next.js returned HTTP 500 while decoding `app/favicon.ico`.
The fourth ICO entry contains a malformed PNG signature. The retry omits this
optional asset only in the copy; this is a manual source intervention, not an
autonomous agent repair.

The CLI now defers inferred service hints and example-only dotenv requirements
only for reviewed existing setups with a full `--run`. Required-variable guards,
other eligibility checks and resource isolation remain enforced. A passing HTTP
probe alone does not establish database business correctness.

## Verified result

The retry through the ordinary CLI (`runtime-cli.json`) passed build, service
health and HTTP readiness. Independent `verify.py` used the application's
installed Prisma client inside its container to create a unique Todo. A GET of
`/` returned HTTP 200, contained `Todo List`, and rendered that exact database
record. After deleting the record through Prisma, another GET no longer rendered
it. See `verification.json`. This proves this database write/read/delete path;
it does not exercise browser form actions, every route or production deployment.

Scoped cleanup removed the pilot's containers, network and generated image;
`cleanup.json` records the post-cleanup checks. The unrelated MariaDB container
was left running. The pilot is no longer running. No model requests were used.

Offline suite: 198 passing tests (`offline.json`). `release_ready=false` remains
in the suite report: passing this pilot does not certify general repository
support or autonomous setup. Node inference and report redaction changes from
the preceding checkpoint remain uncommitted along with this change.

Artifacts include the reviewed `compose.pilot.yaml` (no literal credentials),
failed attempts, successful CLI result, verification script and cleanup evidence.
The ignored working copy lives at `work/postgres-pilot-2026-10-07/app`. Its private
`.env` supplies `PILOT_DB_PASSWORD`; neither that file nor its value is published.

Command used for the successful retry, from the agent repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 \
BUILDX_CONFIG="$PWD/work/postgres-pilot-2026-10-07/buildx" \
DEVOPS_AGENT_STATE_DIR="$PWD/work/postgres-pilot-2026-10-07/state" \
.venv/bin/python -m agent.main validate work/postgres-pilot-2026-10-07/app \
  --existing-setup --compose-file compose.pilot.yaml --run --keep-running \
  --service app --container-port 3000 --timeout 600 --readiness-timeout 120 --json
```

The verification script runs after saving this output as `runtime-cli.json` next
to the script, while the validated containers are still running. Its unique test
record is removed in a `finally` block; owned Docker resources require scoped
cleanup afterward. Manual interventions above are part of this result.
