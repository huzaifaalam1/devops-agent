# Step 3: evidence-backed repository understanding

This describes the step-3 checkpoint. [Step 4](docker-proposals.md) adds preview
and application controls and resolves the remaining generation gap noted below.

The CLI now distinguishes a framework label from eligibility for the first
Next.js/npm/Node 22 workflow. Inspection does not run npm, Docker, project
scripts, or JavaScript configuration.

## Behavior

```sh
devops-agent analyze /path/to/app
devops-agent analyze /path/to/app --json
devops-agent dockerize /path/to/app
```

`analyze` is read-only. Its normal output includes evidence, assumptions, unknowns,
blockers, and suggested next actions. `--json` returns a versioned structure:

- `schema_version`: currently 1.
- `repository`: selected path, discovered files, and candidate app directories.
- `analysis.project`: eligibility, findings, blockers, assumptions, unknowns,
  setup status, possible startup command, and inferred services.
- `components`: per-directory analysis for candidate applications.

Each finding includes a certainty (`confirmed` or `inferred`) and an evidence
path, with a manifest field when applicable. Confirmed describes what the file
states, not proof that the application will run. Service package names indicate
possible dependencies; they do not prove the service is required at runtime.

Eligibility is one of:

| State | Meaning |
| --- | --- |
| `eligible` | No blocker found within the static checks; runtime readiness is unverified. |
| `blocked` | Known scope or metadata problem prevents the requested workflow. |
| `needs_input` | At least one conflict or unresolved assumption needs clarification; other blockers may also exist. |

`dockerize`, `validate --build`, and `validate --run` exit 1 before writing files or
starting Docker commands when eligibility fails. Each blocker has a stable code,
evidence path, and next action. Configuration-only `validate` remains available
for existing Compose configurations outside the generation scope.

If multiple app directories are found, the tool lists their relative paths and
asks which application is intended. Rerun against the selected path. It does not
silently pick a component or run an interactive prompt that would hang scripts.

Existing Docker files are preserved. One Dockerfile plus one Compose file is a
reuse candidate, not proof of compatibility. Partial setups and multiple variants
block generation/build/run until resolved. This intentionally defers the old
platform-based automatic selection to configuration-only validation.

## What is checked

- Parse package JSON and actual dependency sections; descriptions and arbitrary
  string occurrences no longer establish a Node framework or service.
- Reject malformed JSON, duplicate keys, malformed dependency maps, and conflicting
  dependency versions with actionable errors that omit file contents.
- Compare npm v2/v3 lockfile root dependencies and engine declarations with the
  manifest. Report missing, unsupported, or stale lockfiles.
- Reconcile packageManager with npm/yarn/pnpm/bun lockfile evidence.
- Require a declared Node engine compatible with the floating Node 22 image;
  flag conflicting `.nvmrc`, `.node-version`, or numeric Docker Node image tags.
- Recognize a direct `next dev` script, its port/hostname options, and common
  bundler flags. Custom commands, startup hooks, unknown options, non-3000 ports,
  and loopback-only container bindings require review.
- Identify known database, worker, and cloud dependency packages as inferred
  services and conservatively block that out-of-scope workflow.
- Inspect documented environment names and simple Next configuration references;
  show names and evidence without returning values.
- Walk application directories only to the configured depth (default two), pruning
  dependency/build/hidden/work directories before descending. Do not follow
  directory symlinks. Structured metadata readers reject files linked outside
  the selected app and files above 2 MiB.

## Deliberately conservative runtime ranges

This implementation is not a general npm semver parser. It accepts `22`, `22.x`,
`22.*`, `^22.0.0`, `*`, and simple whitespace-separated numeric comparisons that
cover the entire Node 22 line (for example `>=20.9.0` or `>=20 <23`). Explicitly
outside ranges such as `18.x`, `^20.0.0`, or `>=24` are incompatible.

Exact minor/patch pins, partial ranges such as `>=22.1.0`, OR expressions,
prereleases, tags, and other unsupported syntax remain unknown. The floating
image's exact Node version has not been inspected, so the tool requests review
rather than pretending it can honor a specific patch requirement. It never
rewrites a project's runtime declaration to make it pass.

## Environment evidence and its limits

Dotenv precedence is `.env.development.local`, `.env.local`, `.env.development`,
then `.env`; an empty higher-priority value remains unresolved. Values are used
only to check simple nonempty assignments. Quoted empty strings, variable
interpolation, and complex syntax do not count as provided values.

Entries in `.env.example` are documented names, not proof that they are mandatory.
An unresolved documented name asks the user to provide it or clarify optionality.
Simple `if (!process.env.NAME) ... throw` patterns in `next.config.js/mjs/ts`
produce inferred required-variable blockers; dynamic bracket access is unknown.
Configuration matching is heuristic and can also match comments or strings, so
it is labeled inferred and requests clarification rather than claiming execution
proved a requirement.

Arbitrary application source, custom configuration imports, host environment,
secret providers, and Docker environment wiring are not evaluated. Nonempty
local values do not prove Docker passes those values correctly. Full JavaScript
analysis and runtime readiness are outside this step.

## Acceptance results and boundaries

The current suite has **45 passing checks and one expected failure**. The seven
historical G02–G08 cases now pass: missing documented configuration, unsupported
services/runtime/package manager, missing lockfile, ambiguous components, and
partial Docker setup. Their expected-failure decorators were removed.

Additional tests cover metadata errors, false-positive dependency text, stale
lockfiles, environment precedence/redaction, source guards, startup ambiguity,
runtime contradictions, JSON output, scanner boundaries, and validation gates.
Use `tests.run_baseline` to reproduce the complete suite and write fresh evidence
under `work/`; historical `docs/baseline/` snapshots remain unchanged.

**G01 remains open for step 4:** generation still adds `.env` to Compose for a
project with no environment requirements. Templates and runtime readiness logic
are unchanged. Eligibility does not certify lockfile transitive integrity,
Compose semantics, endpoint identity, deployment safety, or production readiness.
No Docker images were built or services started for this step.
