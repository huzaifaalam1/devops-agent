# Step 3: evidence-backed repository understanding

This describes the step-3 checkpoint. [Step 4](docker-proposals.md) adds preview
and application controls and resolves the remaining generation gap noted below.

The CLI now distinguishes a framework label from eligibility for the first
Next.js/npm workflow with a repository-declared Node runtime. Inspection does not run npm, Docker, project
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
block generation/build/run until resolved. Validation accepts explicit `--compose-file` selection; it does not guess among
multiple files, including for configuration-only checks.

## What is checked

- Parse package JSON and actual dependency sections; descriptions and arbitrary
  string occurrences no longer establish a Node framework or service.
- Reject malformed JSON, duplicate keys, malformed dependency maps, and conflicting
  dependency versions with actionable errors that omit file contents.
- Compare npm v2/v3 lockfile root dependencies and engine declarations with the
  manifest. Report missing, unsupported, or stale lockfiles.
- Reconcile packageManager with npm/yarn/pnpm/bun lockfile evidence.
- Infer Node from `package.json` engines.node, intersecting numeric runtime-file
  requirements and the locked Next.js Node engine range. Flag conflicting numeric
  Docker tags and declarations rather than forcing a Node 22 template.
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

## Node version inference

`analysis.project.node_version` is the selected numeric Docker tag. The proposal
uses it in `FROM node:<tag>` and explains the source. Selection requires
`package.json` `engines.node`; `.nvmrc` and `.node-version` constrain it when
present, as does `package-lock.json`'s resolved Next.js `engines.node` metadata.
Missing or conflicting declarations block generation. Runtime files and package
configuration are read as data, never executed.

The bounded parser follows stable numeric npm range semantics for exact versions,
major/minor and x ranges, caret, tilde, comparisons, whitespace conjunctions and
`||` alternatives. Prereleases, hyphen ranges, lifecycle aliases such as `lts/*`,
malformed expressions and requirements with no explicit positive major lower
bound require clarification. It is not a complete npm semver implementation.

Selection chooses the lowest compatible stable line across the intersection,
then uses the broadest major/minor/patch tag wholly contained in it. Examples:
`24` → `node:24`; `24.14.0` → `node:24.14.0`; `^20.9.0` → `node:20.9`;
`>=18` plus locked Next.js `>=20.9.0` → `node:20.9`. This is a deterministic
compatibility policy, not a recommendation of the newest or currently supported
Node release. Major/minor tags can receive newer patches. Image availability,
transitive package requirements, installability and app readiness still require
build/runtime verification. No implicit Node 22 fallback remains.

Existing numeric Docker tags are checked against the declared requirements;
ARG-based Docker image selection is not evaluated statically. The explicit
existing-setup mode retains its separate reviewed-build behavior. Port repair
recognizes the generated Dockerfile for the selected version and does not change it.

Semantics references: [npm engines](https://docs.npmjs.com/cli/v11/configuring-npm/package-json/#engines)
and [npm semver ranges](https://github.com/npm/node-semver#ranges).

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

## Unsupported frameworks

Projects without a declared Next.js dependency remain analysis-only and blocked
for automated setup/runtime validation. Their framework/service detection and
component candidates remain visible, but npm lockfile, Node 22, Next startup and
template-completeness checks are not presented as defects to repair. The guidance
is to preserve the existing stack and inspect its own documented workflow.
