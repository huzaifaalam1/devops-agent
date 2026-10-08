# Package-declared Node inference verification

October 7, 2026. Prior pilot fixes were committed and pushed as `8113162` before
this new change. Node inference remains uncommitted for review.

195 offline tests passed. An additional 6,650 membership comparisons across 19
supported range forms and 350 stable versions matched the locally installed npm
semver implementation. This sampling is not a proof of all semver behavior; the
parser explicitly rejects unsupported syntax.

The pinned minimal Next.js test application was given matching package.json and
lockfile root `engines.node: 24.14.0` declarations. The agent proposed and applied
a Dockerfile with `FROM node:24.14.0`, then the ordinary CLI `validate --run`
built and started it (without the existing-setup bypass). Docker exec confirmed
`v24.14.0` inside the owned container. Independent HTTP GET returned 200 and the
fixture-specific page marker. Scoped shutdown, validation-image removal and
zero remaining project containers were verified. Runtime took about 45 seconds.

This is real Docker execution of a controlled test fixture, not a second
unmodified open-source repo success. The earlier external pilot remains recorded
separately. No original cloned application was modified. The known over-redaction
and database-pilot gaps are separate from this Node selection change.

See `runtime.json` for the generated proposal, application result, independent
check and cleanup; `verification.json` records tested agent source hashes. No
model API calls were required. Build cache is retained and no user cache or
personal files were deleted by the assistant.
