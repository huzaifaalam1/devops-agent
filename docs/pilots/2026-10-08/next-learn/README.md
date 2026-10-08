# Assisted next-learn npm compatibility pilot

Upstream `vercel/next-learn`, commit
`bb2558441a6673ab76c89914c25018bffa27a2ba`, application
`basics/learn-starter`. Original checkout remains unchanged.

This upstream application uses pnpm, not npm. It is not evidence of native pnpm
support. Manual preparation in an ignored copy:

1. Pin direct dependencies to upstream pnpm lockfile versions: Next 16.0.10,
   React 19.2.1 and React DOM 19.2.1. The original manifest uses `latest`.
2. Move pnpm lock/workspace files and its `.npmrc` outside the application copy.
3. Remove the stale `.nvmrc` Node 18 pin in the copy. Upstream's locked Next
   requires Node >=20.9.0, incompatible with that pin. Keep the manifest's >=18
   requirement; the agent intersects it with the new npm lock's Next requirement.
4. Generate package-lock.json using npm with `--package-lock-only --ignore-scripts
   --no-audit --no-fund` and a private cache. This resolves a new transitive npm
   tree, not a byte-identical conversion of the pnpm lockfile.
5. Apply the agent's generated Docker proposal (Node 20.9), then change its host
   port to an ephemeral loopback port because another application uses port 3000.

Application JavaScript, CSS and public assets are unchanged. File hashes are in
`source-comparison.json`; adapted metadata and generated Docker files are retained
alongside this report. Node selection establishes range compatibility, not a
recommendation about supported Node releases or production security.

Run uses normal `validate --run --keep-running`, without `--existing-setup`.
The copied application is `work/next-learn-pilot-2026-10-08/app`; Buildx config and
agent state are in sibling `buildx` and `state` directories. No model calls.

## Result: passed with documented manual preparation

The normal CLI built and started the application successfully (`runtime.json`).
An independent GET returned HTTP 200 and contained `Welcome to`, `Next.js!`,
`pages/index.js` and `Documentation`. `/vercel.svg` also returned HTTP 200 and SVG
content. Docker exec confirmed Node v20.9.0. See `verification.json`.

The verification script then removed only this pilot's containers, network and
owned build image; no project volumes remain. Existing media-facility and MariaDB
containers were left running. The pilot is no longer running.

This brings the external pilot count to **3/4 runtime-verified with manual
preparation**: docker-nextjs-sample, nextjs-docker-postgres-template and this
adapted next-learn starter. Django/Vue remains outside the current execution
scope. This does not mean three repositories worked unmodified or autonomously.
No agent source changes were needed for this pilot, so the prior 198-test result
was not rerun. Real build and HTTP checks are the new verification evidence.

Reproduce after preparing the copy as described above:

```sh
PYTHONDONTWRITEBYTECODE=1 \
BUILDX_CONFIG="$PWD/work/next-learn-pilot-2026-10-08/buildx" \
DEVOPS_AGENT_STATE_DIR="$PWD/work/next-learn-pilot-2026-10-08/state" \
.venv/bin/python -m agent.main validate work/next-learn-pilot-2026-10-08/app \
  --run --keep-running --timeout 600 --readiness-timeout 120 --json \
  > work/next-learn-pilot-2026-10-08/runtime.json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python work/next-learn-pilot-2026-10-08/verify.py
```

The saved verification script expects the report and `app` directory alongside
it, verifies content, and performs scoped cleanup even if content checks fail.
