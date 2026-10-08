# Successful external Next.js runtime pilot

October 7, 2026. The Docker Next.js sample (development revision
`3d7cd2d9ab13f19bbba780e095d99f6bdadc89d4`) built and started through the agent.
Agent readiness returned HTTP 200. An independent GET verified HTTP 200 and both
“Next.js Resources” and “Docker Resources” in the page body. The container and
port were independently linked to the agent's Compose project via Docker inspect.
After verification, scoped shutdown removed the pilot container/network and
validation image; no project containers remained. The app is no longer running.

## Exact obstacles and interventions

1. The agent previously applied Node 22 template prerequisites to an existing
   Dockerfile. The upstream Dockerfile.dev pins Node 24.14.0 and explicitly prefers
   npm when its lockfile exists. Added opt-in `--existing-setup`, requiring explicit
   Compose selection, to defer only package-manager ambiguity and Node template
   compatibility checks to build/runtime evidence. Other eligibility and all
   resource isolation checks remain in force. 191 offline tests pass.
2. Upstream Compose includes alternative deployments, fixed container names and
   development sync. A human-equivalent preparation step added `compose.pilot.yaml`
   in a copy: one app using the unmodified upstream Dockerfile.dev, an ephemeral
   localhost port, and telemetry disabled. No upstream source, dependency or
   lockfile changes were made. This is assisted existing-setup validation, not
   autonomous conversion or success on unchanged upstream Compose.
3. First build failed because the sandbox denied default Buildx activity writes.
   Preserved that failed attempt as runtime.json. The retry used a private writable
   BUILDX_CONFIG directory; runtime-retry.json records the successful build/start.
4. Redaction over-matched the public environment value `1`, corrupting the reported
   loopback URL. This reporting defect remains open. The independent check used
   Docker's verified port mapping instead; it did not trust a repaired report URL.

## Reproduction

From the agent checkout (the prepared copy remains in work):

```sh
BUILDX_CONFIG="$PWD/work/pilot-runtime-2026-10-07/buildx" \
DEVOPS_AGENT_STATE_DIR="$PWD/work/pilot-runtime-2026-10-07/state" \
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m agent.main validate \
  work/pilot-runtime-2026-10-07/app --existing-setup \
  --compose-file compose.pilot.yaml --run --timeout 600 \
  --readiness-timeout 90 --json
```

The recorded run also used `--keep-running` to permit the independent GET, then
was stopped explicitly using its unique project scope. Omitting that flag above
lets the agent clean up automatically. Shared build cache is retained. Host free
space fell during the build; inspect storage before further image builds rather
than pruning unrelated user resources.

## Scope

One real application startup is now verified. Django/Vue and the database pilot
remain unverified for runtime; no broadened-stack success is claimed. The initial
four-repository screening is retained. One failed infrastructure attempt and one
successful retry are recorded, as are the manual configuration intervention and
remaining redaction defect. No model calls were required. Changes are uncommitted.
