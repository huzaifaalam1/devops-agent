# Using V2

Activate the project's Python environment, configure the provider key in the
agent checkout's ignored `.env`, and select one application directory:

```sh
devops-agent chat /absolute/path/to/app
```

Examples of requests:

- “Run this app locally with Docker, verify the page, and leave it running.”
- “Use compose.dev.yaml to validate the existing setup. Preserve the app files.”
- “Set up this Django app on port 8000. Don't run migrations.”
- “Prepare a new disposable PostgreSQL environment and show me the migration plan.”
- “What containers belong to this repo?” / “Stop this repo's container.”
- “Prepare AWS files and validate them locally.”

The agent reviews provider use and each mutation separately. Read the exact files,
container scope and database target in the review. Answer `yes`, `no` or `pause`.
A tool being available is not an approval. Resuming a paused session requires a
fresh review; stale inputs invalidate earlier grants.

`/inspect` uses local evidence; `/status` shows the current request; `/debug` exposes
technical details; `/resume ID` reopens a conversation; `/repo PATH` changes the
selected application. `/cancel` cancels a pending request. During a synchronous
running validation, Ctrl-C interrupts the operation and triggers scoped cleanup.
Read the resulting cleanup status: an interrupted or failed cleanup is not proof
that resources are gone. `/exit` does not stop a deliberately retained service;
ask to stop it first when that is your intent.

If port 8000 is occupied, free it yourself and retry. The agent must not stop its
owner or silently choose another Django port. A rate-limit error ends the request
with retry timing; wait before submitting another request. There is no paid fallback.

## Supported evidence and limits

- Next.js: one npm application, with adequate repository evidence for generated
  setup. Explicit existing Compose validation can defer generation-only Node or
  package-manager checks; build/runtime evidence still decides the outcome.
- Django: one pip application, pinned supported dependencies, a declared Python
  version, statically understood settings and explicit local database scope.
  Imported/dynamic settings, ambiguous application roots or unsupported dependency
  formats may require preparation. “Django detected” does not mean runnable.
- PostgreSQL: generated disposable environment only; preparation and forward
  migrations have separate reviews. Existing/external databases are not adopted.
  Stopping the disposable tmpfs database loses its data.
- Repair: bounded supported corrections, such as an existing public readiness
  route. No arbitrary source rewrite, automatic authentication bypass or endless
  retries. HTTP readiness does not verify every application feature.
- AWS: local ECS Fargate/CloudFormation artifacts and schema checks only. Install
  the optional `aws-validation` dependencies for cfn-lint. Required image, network,
  roles, secrets and production decisions remain explicit prerequisites. No cloud
  resources, IAM changes, CI pipelines or deployment are performed.

For independent command-line inspection and exact options use
`devops-agent --help`, `devops-agent validate --help`, and `devops-agent aws --help`.
See [the terminal guide](../terminal.md) and [AWS preparation](../step9/README.md).
