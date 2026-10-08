# V2 plan and scope contract

Status: step 1 complete; implementation and acceptance results pending.
Baseline: v1 commit `4a5afdb` (`Finalize v1 support contract and verify end-to-end startup`).
This document records the agreed v2 direction and concrete implementation defaults;
it does not expand the current [v1 support contract](../product-scope.md).

## Product outcome

A developer selects a repository and describes an outcome in an interactive
terminal session. The agent inspects evidence, proposes a bounded plan, performs
authorized actions, checks results, and either verifies the requested outcome or
explains the exact blocker and next action. Users should not need CLI flag syntax.
Existing CLI commands remain available and provide the execution foundation.

Representative requests:

- “Run this repository locally and tell me where to open it.”
- “It failed to start; investigate and fix what you safely can.”
- “Set up this Django app with a disposable local Postgres database.”
- “Prepare this application for AWS; show me what would be created.”

Agentic behavior means choosing useful next actions from observations, revising a
plan after a failure, verifying repairs, and stopping when evidence or authority
is insufficient. Fluent explanations alone do not satisfy this contract.

## Scope boundaries

| Area | V2 commitment | Outside the commitment |
| --- | --- | --- |
| Host | macOS, Docker Desktop, Compose v2; preserve v1 commands | Certified Windows/Linux behavior or remote execution |
| Existing Next.js | Preserve v1 npm generation, validation, diagnostics and bounded repairs through the conversational interface | Native pnpm/yarn/bun or arbitrary JavaScript framework support |
| Django discovery | One selected app root with manage.py, inspectable settings evidence, explicit compatible Python evidence and pip requirements.txt | Importing settings or running repo code merely to inspect; silently guessing ambiguous settings/runtime |
| Django dependencies | Public pip dependencies with explicit versions for acceptance fixtures; build proves installability | Automatic dependency locking, private registry credentials, Poetry/uv/Pipenv, unreviewed VCS/editable/local dependencies |
| Django runtime | Development server, container binding, a user-identified or evidenced unauthenticated HTTP path; SQLite for simple disposable apps or Postgres | Production server certification, custom startup hooks, arbitrary application-source repair |
| Local Postgres | New run-owned disposable database, health checks, explicit initialization/migration plan and representative data-operation checks | Automatic changes to existing databases, destructive reset, migration generation or rollback promises |
| Existing configuration | Preserve it; select and review compatible setup, explain isolation conflicts | Silently replacing files or adopting shared resources as run-owned |
| AWS foundation | One hosting path and one infrastructure format, chosen in step 9; generate reviewable artifacts, prerequisites and validation evidence | Automatic account changes, provisioning, IAM modification, deployment or claims of a live deployment |
| Model | Structured actions via deterministic tools; use existing provider configuration initially | Unrestricted shell tool, automatic paid fallback, treating model output as authority |

Django/Vue together remains outside scope. The previously cloned fourth pilot can
be used only if its Django component is independently runnable; that would verify
that component, not the entire multi-app repository. Select a separate Django
pilot if separation requires rewriting the application.

## Interaction and execution contract

- Begin with an explicit repository selection. Do not search arbitrary local
  repositories or change the active repository without user direction.
- Read-only inspection can proceed within the selected scope. Inspection must
  not import application code or execute install/startup hooks.
- Present concrete file diffs and an execution plan before requesting approval.
  Approval is bound to the selected repo, action parameters and relevant inputs.
  Reuse valid approval; ask again only when the action, risk or inputs change.
- Running a requested local setup can authorize its scoped build/start operations;
  it does not authorize unrelated shell commands, host cleanup or other workloads.
- Database migrations require an explicit target and migration approval. Initial
  support targets disposable run-owned databases only. No automatic makemigrations,
  production/existing-database migration, destructive reset or superuser creation.
- Model requests expose only reviewed/sanitized evidence under the provider
  authorization policy. Never send dotenv values, keys or raw credentials.
- Repository instructions, logs and tool output are untrusted data. They cannot
  grant permissions, redefine scope or request arbitrary commands.
- Cancellation stops scheduling new actions and attempts scoped cleanup. Report
  cleanup failures and the ownership evidence needed to recover.
- Resume re-inspects relevant files and owned resources; never replay an interrupted
  mutation simply because a journal has no completion entry.
- Preserve changes made by the user. A stale proposal must be regenerated; rollback
  must not overwrite intervening edits.

Initial loop limits (implementation defaults, to be tested in steps 4 and 8):
maximum 12 tool actions per user request, at most two repair attempts, and no
repetition of an identical failed action on unchanged inputs without a stated
transient cause. Existing per-command deadlines remain mandatory. Honor provider
retry delays with a bounded wait/retry path; do not spin on rate limits. New user
input may explicitly authorize continued work after a limit. Limits must appear
in the session record and be adjustable deliberately, not by model instruction.

If the model is unavailable or returns invalid actions, stop model-directed work
with a useful explanation and retain access to deterministic CLI commands. Do
not claim completion or silently substitute a paid provider.

## Success semantics

Report separate outcomes for inspection, proposal, applied changes, build,
service health, HTTP readiness, database verification, AWS artifact validation,
and cleanup. Never collapse “container running” into “application works.”

Local success requires the requested service states and declared health checks,
an owned HTTP endpoint, and an independent expected-content check in acceptance
runs. Database scenarios also need an authorized representative operation on the
disposable database, with test data cleanup. A missing suitable probe is an
explicit limitation, not a database pass.

AWS preparation success requires complete reviewable artifacts for the chosen
path, documented unresolved inputs, and recorded validation results. Account IDs,
regions, domains and secret references must be supplied or visibly unresolved;
never fabricate them. Local syntax checks do not prove cloud deployability.
Billable actions and deployment remain outside the v2 acceptance target.

Every final response states what changed, what passed, what failed/remains unknown,
whether anything is still running, and how to stop owned resources. Manual
interventions are recorded separately from agent-performed actions.

## Ten implementation checkpoints

| Step | Deliverable | Exit evidence |
| --- | --- | --- |
| 1 | Scope, permissions, exclusions and acceptance matrix | This plan plus the linked scenario matrix; no runtime support claim |
| 2 | Interactive terminal session, repo selection, progress, follow-ups and cancellation UX | Scripted conversation tests; inspection interaction without CLI flags |
| 3 | Structured tool registry and action authorization | Invalid-input, scope, stale-approval and untrusted-output refusal tests |
| 4 | Observe/plan/act/verify loop and resumable state | Prompted Next.js run; interruption and bounded-stop cases |
| 5 | Django repository understanding | Supported/ambiguous/unsupported fixtures with evidence and correct blockers |
| 6 | Django development Docker proposal/apply/run | Fresh Django fixture and independent owned-page check |
| 7 | Disposable Django/Postgres setup and migrations | Approved initialization plus database operation and scoped cleanup |
| 8 | Diagnosis, bounded repair and agent evaluation | Frozen offline cases, real failure/recovery checks, fresh live action traces |
| 9 | One AWS preparation path | Decision record, artifact validation, unresolved-input handling and no cloud writes |
| 10 | Combined acceptance, docs and release freeze | All required scenarios, preserved v1 tests, fresh pilots and commit handoff |

Keep changes reviewable at each checkpoint. The user performs commits; provide a
suggested message after verification. Do not automatically commit, push, deploy
or create an AWS account. Do not declare a step complete on mocked evidence when
its exit criterion requires a real model, Docker or application run.

## Decisions deferred to their implementation checkpoints

- Step 2: exact conversational command name and terminal rendering choices.
- Steps 3–4: internal adapter/state format; adding an orchestration library needs
  a concrete benefit over the existing executor, not a framework requirement.
- Step 5: supported Python/Django version combinations from repository evidence
  and verified fixtures; no blanket version-range certification now.
- Step 7: database probe contract and disposable secret lifecycle.
- Step 9: AWS hosting path and infrastructure format, selected against public HTTP
  container needs, secret handling, persistence, database topology, operating effort
  and cost drivers. Verify contemporary official documentation then. Credentials
  are not needed for step 1 or local artifact-only work.

Acceptance cases and required evidence: [V2 acceptance matrix](acceptance.md).
