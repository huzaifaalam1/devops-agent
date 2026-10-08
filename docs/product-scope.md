# v1 support contract

v1 is a bounded local development assistant for a single **Next.js/npm** app on
macOS with Docker Desktop and Compose v2. It inspects prerequisites, previews
Docker files, applies explicitly authorized changes, verifies local readiness,
and explains failures. It is not a general autonomous DevOps agent.

## Supported workflows

| Workflow | Contract |
| --- | --- |
| Generate a development setup | One app directory; Next.js declared in package.json; npm package-lock v2/v3 matching root declarations; explicit engines.node; supported direct next dev command on container port 3000. |
| Infer Node | Intersect package engines, numeric runtime files and the locked Next.js engine requirement. Conflicts or unsupported syntax block generation. Selection proves range compatibility, not release lifecycle/security status. |
| Apply changes | Preview first; `--apply --expect ID` binds application to the reviewed proposal. Existing files, dirty targets and changed inputs are guarded. Private recovery records support bounded restoration. |
| Validate generated setup | Resolve Compose, build, start a unique project, check expected services and declared health checks, then probe its owned HTTP endpoint. Default behavior cleans up after checking. |
| Validate reviewed existing setup | Explicit `--existing-setup --compose-file FILE`; Next.js eligibility and isolation remain required. Full `--run` may defer package/service hints and example-only environment requirements to observed runtime behavior. This does not generate databases or migrations. |
| Handle a host-port conflict | Refuse the occupied binding without stopping its owner. Reviewed Compose port changes or the bounded generated-file port repair can select another host port. Container target remains unchanged. |
| Diagnose / repair | Evidence-backed diagnosis; bounded host-port or user-supplied readiness-path repair only. No general application-source repair loop. |
| Optional model advice | Explicitly authorized, sanitized explanation requests; deterministic code controls actions. No API key is needed for the core workflow. |

Generation also refuses ambiguous app directories, workspace/mixed-stack evidence,
custom npm configuration, unresolved environment requirements and service hints.
Pass the actual application directory. A repository being recognizable does not
mean it is eligible to generate or run.

## User-supplied prerequisites

- Python 3.10+ (recorded testing uses Python 3.12), Docker Desktop and Compose v2.
- Authorization to execute the selected repository and access to its dependencies.
- Network access for image/package downloads, sufficient Docker storage, and a
  free chosen host port. Acceptance runners require at least 8 GiB host free space.
- Real application configuration supplied locally. Generated setups mount
  supported development dotenv files read-only; build contexts exclude them.
  Never place application credentials in the agent's optional provider config.
- An unauthenticated HTTP readiness path. HTTP 2xx proves that path responds;
  it does not establish every route, browser behavior or database transaction.

## Success and failure semantics

Configuration-only success is not a build or startup pass. Build-only success is
not readiness. A runtime pass requires service state, declared health checks and
HTTP readiness tied to the owned project, within deadlines. JSON records the
stage, evidence, environment state, cleanup and unverified conditions. Failure
returns a nonzero status and actionable guidance; uncertainty remains explicit.

`--run` normally leaves the environment stopped after verification.
`--keep-running` retains only a successful run and reports its URL and scoped
stop command. Cleanup never stops unrelated workloads. Review cleanup errors;
a failed cleanup means owned resources may remain.

## Evidence and limits

The [v1 closeout](releases/v1.md) records fresh end-to-end and offline results.
Three external pilots passed **with manual preparation**:

- docker-nextjs-sample: manually isolated existing Compose configuration.
- nextjs-docker-postgres-template: isolated configuration, explicit Prisma
  initialization and omission of a malformed optional favicon; a database record
  was created, rendered, deleted and confirmed absent.
- next-learn starter: explicitly adapted pnpm metadata to npm in a copy, preserved
  direct locked versions, reconciled a stale Node pin and selected another port.

These are not three autonomous, unmodified-repository successes. Original
checkouts stayed unchanged. Django/Vue is excluded, not a fourth passing pilot.

## Outside v1

Native pnpm/yarn/bun generation, Django/Vue/other framework execution, monorepo
orchestration, automatic database provisioning/migrations, worker/cloud setup,
private-registry build credentials, authenticated probes, production deployment,
CI/CD generation, Kubernetes/Terraform/AWS and unrestricted model execution.
Named/shared resources and writable host bind mounts can be refused by isolation
policy even when ordinary Docker Compose accepts them. Use a reviewed disposable
configuration; do not disable isolation to force a pass.

Windows/Linux host coverage, production builds, release-lifecycle selection and
independent model-quality evaluation are not certified by this release.
