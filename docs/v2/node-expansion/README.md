# Node/Vue foundation follow-up

This follow-up addresses the media-facility chat session that rejected Vue as
unsupported and then offered an approval for an unsupported multi-app root.
Changes are uncommitted. The earlier V2 acceptance results remain historical;
they did not establish general Node or mixed-stack support.

## Behavior

- Shared npm dependency/lockfile inspection and Node runtime selection now feed
  framework-specific startup adapters instead of requiring every app to be Next.js.
- Next.js retains its tested development workflow. Vue/Vite and other Vite apps
  use their development scripts, literal configured/CLI ports, explicit container
  bind address and strict port selection. The user's Node-wrapped Vite command is
  recognized. Vue CLI's `serve` script has static adapter coverage.
- Direct `node entry.js` / `.mjs` / `.cjs` servers can generate setup when a single
  literal listening port is evidenced. Dynamic ports, custom shell chains and
  lifecycle hooks require clarification; the agent does not execute configuration
  to guess a result.
- Vite's locked Node engine range can provide compatibility evidence when the
  project has no engines declaration. This is explicitly an inference, not an
  assertion about the application's intended support policy. New Node/Vue images
  use the selected Debian slim Node tag; builds still verify installability.
- Explicit existing Compose validation may defer generation-only scripts,
  lockfile and runtime requirements. Unsupported/multiple applications and
  database ownership boundaries remain blockers. Validation still enforces
  isolated resources, readiness and scoped cleanup.
- Runtime eligibility is checked before offering an execution approval.
  Describing two components is not treated as changing the selected repository.
- Expected review errors report a sanitized reason. Compose secret redaction
  covers prefixed names in mapping/list/inline forms and assignment text.

Generation remains **npm-only**; pnpm/yarn/bun projects may use compatible reviewed
existing Docker configurations. This does not yet orchestrate Django + Vue + an
existing persistent PostgreSQL database as a whole repository. AWS preparation
remains its separately tested Next.js/Django contract, not production Vite hosting.

## Verification status

The first real Vue pilot passed using an isolated copy of the user's tracked
frontend files (working-tree content, no application/dependency changes). It built
with Node 20.19, served port 3000, and returned HTTP 200 for `/`, `/src/main.js` and
`/src/App.vue`. The latter checks exercise Vite's JavaScript/Vue transformation.
Source hashes were preserved; test resources were stopped and removed; unrelated
MySQL remained running. This does **not** verify browser interaction, backend APIs,
authentication or database-backed business operations.

The final candidate uses prompt `loop-action-v22`. Offline: **351 tests passed**.
Final frozen `eval-03` **passed both cases** and covers the direct Node fixture and the real Vue frontend;
`regression-03/nextjs.json` is a targeted Next.js regression, not a rerun of the
entire historical five-case step-8 suite. Reports are retained under `evidence/`.

Earlier attempts are retained: the first scope harness failed because Python
stdin cannot launch macOS spawn workers; a subsequent scope attempt hit HTTP 429.
The next answer correctly refused multi-app execution but made an unsupported
SQLite claim. The prompt now explicitly treats uninspected child database and
startup requirements as unknown. The final read-only scope response respected
that boundary and performed no mutations. Its selection wording remains less
precise than the literal `/repo PATH` command documented below; the automated
scope check verifies completion and allowed tools, while answer quality requires
manual review. Duplicate inspection was prevented by the existing loop guard.

The first Next.js attempt stopped at a transient port-3000 conflict after Vue
cleanup (no listener remained); the second failed on provider connection. The
third passed build, HTTP page marker, conversation resume and scoped cleanup.
These failed attempts are not counted as runtime passes.

## Use

For this frontend, select the actual app directory rather than the multi-app root:

```sh
devops-agent chat /Users/huzaifaalam/Desktop/repos/media-facility/media_facility_frontend/media_facility_frontend
```

Then ask to generate Docker setup, build and verify the frontend, and leave it
running. Provider use, file application and runtime execution each retain their
review boundaries. Starting only the frontend does not start its backend.

For a new frozen pilot set, use `tests.node_expansion_smoke --freeze --directory
work/node-expansion/NEW`, then `--case vue` and `--case node` with that directory.
Use `PYTHONDONTWRITEBYTECODE=1`; run model cases sequentially. Source/candidate
changes require a new freeze. `tests.node_scope_smoke --output FILE` checks the
multi-app scope explanation without granting mutations.

Port/binding flags follow the official [Vite CLI](https://vite.dev/guide/cli)
and [Vue CLI service](https://cli.vuejs.org/guide/cli-service.html) interfaces.
