# Step 4: reviewable Docker development setup

`dockerize` now previews by default. This is an intentional change from the old
immediate-write behavior. No prompt or file write occurs during preview.

```sh
devops-agent dockerize /path/to/app
devops-agent dockerize /path/to/app --json
devops-agent dockerize /path/to/app --apply
# Require the exact ID printed by a previous preview:
devops-agent dockerize /path/to/app --apply --expect <proposal-id>
```

A proposal contains its destination, development-only purpose, status, blockers,
file operations, reasons, unified diffs, preserved files, and a content-derived ID.
`--json --apply` also reports which files were created or updated. Decline a
proposal by not applying it. Unsupported projects still exit 1 with next actions.
`--expect` without `--apply`, or with a stale ID, exits 1 without writing.

The proposal is recomputed before application. Changes to inspected metadata,
configuration, environment files, the proposal itself, or target files invalidate
it. Existing target files are never silently overwritten. New files use exclusive
creation; a `.dockerignore` update requires the reviewed prior content hash.
A failed write attempts to remove only new files owned by the operation and
restore its updated file. This is best-effort recovery, not a filesystem-wide
transaction or protection against all concurrent writers. Durable rollback and
broader execution controls remain step 7.

## Generated setup

- **Dockerfile:** Node 22; explicit development environment; `npm ci --include=dev`
  using package.json and package-lock.json; `npm run dev` preserves the startup
  script already checked by repository understanding. Dependency manifests are
  not modified. This is not a production image.
- **Compose:** one app service, bound to `127.0.0.1:3000` on the host. No database,
  cloud credentials, or additional service is invented.
- **Environment:** an app without dotenv files receives no environment-file
  requirement. Existing `.env`, `.env.development`, `.env.local`, and
  `.env.development.local` files are mounted read-only at their original names
  for Next.js to load with its development precedence. Bind mounts do not create
  missing host paths. Environment values are never serialized into the proposal
  or copied into image layers. `.env.example` is documentation, not a runtime
  configuration file, and is not mounted.
- **.dockerignore:** excludes host dependencies, generated files, and dotenv
  files. Existing rules are preserved; required exclusions are appended last in
  a visible diff, after any earlier negations. Existing custom patterns can still
  exclude required application files; review them and validate the build.

Missing documented environment values and other step-3 blockers remain blockers;
this step does not invent defaults or credentials. Custom `.npmrc` configuration
also requires review before generation, rather than silently copying registry
credentials or ignoring installation requirements.

## Existing and partial setups

A complete existing Dockerfile/Compose pair is returned as `unchanged`; contents
are not rewritten or included in a generated diff. Its compatibility is still
unverified. A second normal `--apply` after generation is likewise a no-op.

Partial or ambiguous setups remain blocked with an explanation and next action.
The tool does not guess how to pair a custom Dockerfile with new Compose, overwrite
an existing file, or equate an incomplete setup with success. Resolve the existing
configuration before retrying. This is deliberate handling, not automatic repair.

The internal `generate_docker_files(path, analysis)` API was replaced by
`propose_docker_files(path)` and `apply_docker_proposal(proposal)`. Both use fresh
repository evidence rather than trusting a caller-supplied framework label.

## Verification

The full suite has **59 passing checks and zero expected failures**. The original
G01–G08 regression cases all pass. Added checks cover read-only preview, JSON
output, reviewed IDs, lockfile preservation, dotenv privacy, ignore-file diffs,
idempotence, stale/tampered proposals, failed-write cleanup, and existing setups.

Real `docker compose config --quiet` also passed for generated no-dotenv and
with-dotenv fixtures. No images were built or containers started. These results
verify proposal behavior and Compose syntax, not npm installation, application
readiness, endpoint identity, or production safety. Step 5 remains responsible
for making runtime validation trustworthy.

Run `.venv/bin/python -m tests.run_baseline --output work/step4-tests.json` for
fresh test evidence. Historical evidence in `docs/baseline/` remains unchanged.
