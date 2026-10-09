# Bounded persistent agent loop — step 4

The default `devops-agent chat PATH` now uses LangGraph 1.2.14 with a local SQLite
checkpointer (langgraph-checkpoint-sqlite 3.1.1). The existing CLI remains the
execution foundation; the structured registry enforces approval and repository
scope. This is a small single-agent loop, not general shell or source-code repair.

## Use

Reinstall the editable package to obtain the pinned dependencies:

```sh
.venv/bin/python -m pip install -c requirements-baseline.txt -e .
.venv/bin/devops-agent chat /path/to/app
```

Configure the existing agent `.env` with `GROQ_API_KEY`; do not put that key in the
application repository. The configured provider/model is unchanged. No automatic
paid fallback exists. `chat --offline PATH` preserves the step-2 read-only shell
and needs no model key. `/inspect` in the persistent chat performs local inspection.

Example request: “Set up this repository with Docker, verify it, and leave the
successful app running.” The terminal first inspects files, then displays the
sanitized outbound context and provider/model. Approving this review authorizes
up to 12 bounded model requests for that user request, including later sanitized
tool summaries. Each file mutation or Docker action receives a separate concrete
review. Enter `yes`, `no`, or `pause`; other text does not grant permission.

Useful commands: `/inspect`, `/status`, `/resume ID`, `/repo PATH`, `/cancel`,
`/help`, `/exit`. At an approval, `pause` preserves the request. The printed
conversation ID can be reopened in a new process:

```sh
.venv/bin/devops-agent chat /path/to/app --resume CONVERSATION_ID
```

Follow-up requests start a fresh bounded graph run in the same selected repo;
they do not silently inherit execution approval. Completed sessions show recorded
evidence when reopened, not a new assertion that their services are still healthy.
The model's `finish` decision is labeled a model stop; only the runtime validator
can establish the `verified` outcome.

## Flow and bounds

The graph runs inspect → decide → review when needed → execute → decide.
Successful runtime validation ends with deterministic readiness evidence. Blocked
or unsupported requests stop with an explanation. The model chooses only from
typed tool variants plus `finish`; there is no free-form arguments string or shell
command. Both provider structured output and local validation constrain parameters.

Limits per request: 12 tool actions (including initial inspection), 12 provider
requests, two failed tool outcomes, bounded 24,000-character planner context,
1,400 output tokens per model response and a 60-second provider transport deadline.
Tool timeouts and cleanup bounds remain enforced by the existing executor.
Repeated read-only actions are compared using their returned evidence; mutation
actions use the full repository fingerprint. Checking for repeated read-only
evidence can rescan local files. Installed dependencies and build output therefore
do not prevent initial inspection. Docker approval fingerprints up to 250,000 entries /
2 GiB using streaming reads, including installed dependencies and generated files.
Internal symlinks are fingerprinted along with their in-repository targets; external,
broken, and Git-metadata links are refused. File patch approval fingerprints only
the selected file and repository identity; a refusal now displays its specific
reason instead of reporting a model configuration failure. There is no automatic provider retry: a 429 reports an
available retry delay, stops, and requires a new request after waiting.

This checkpoint can replan by selecting a different supported validation action,
for example a supplied health path. It does not introduce new application repair,
port editing, Django, migration or AWS capabilities. Those remain later steps.

## Persistence and approval

Private state lives at `DEVOPS_AGENT_STATE_DIR/conversations.sqlite`, or the
existing default `~/.local/state/devops-agent` directory. It must be outside the
application/build context. Directory permissions must be 0700 and the database
0600, owned by the current user. Symlinked database files are refused. The JSON/
MessagePack serializer disables pickle fallback and arbitrary module loading.
LangSmith tracing is disabled for graph invocation; no tracing service is required.

Persisted data includes redacted requests, bounded observations, action parameters,
checkpoint transitions and operation outcomes. Keys, live approval grants and raw
configuration previews are not checkpointed. A displayed preview stays in memory;
its checkpoint carries only the operation identifier. Known-secret redaction is
not a guarantee of recognizing every arbitrary sensitive string: review outbound
context and do not paste credentials into prompts. State has no automatic retention
policy in this checkpoint; it is a private local file, not encrypted storage.

A separate SQLite operation ledger records `started` before executing a tool and
`complete` with sanitized results afterward. On resume:

- Completed operations reuse recorded evidence without repeating the side effect.
- An operation recorded as started with no completed result stops in `reconcile`.
  Inspect the existing action journals and owned Docker resources before retrying.
- Missing in-memory approval is never reconstructed from a saved `yes` response.
  A pending review is regenerated or execution stops for fresh review.
- Resuming a planning boundary re-inspects the repo. Counts and repetition guards
  remain bounded; provider consent is requested again after process restart.
- A per-conversation process lock covers checkpoint reading/updating/resuming, so
  two terminals cannot concurrently advance the same conversation. Existing
  project mutation locks remain separate.

This favors stopping over claiming exactly-once execution across an uncertain
process crash. It cannot undo external effects or inspect every interrupted
operation automatically. Ctrl-C/EOF ends terminal interaction; supported executor
cleanup still applies. Cancellation does not shut down previously retained services.
Use the recorded scoped stop command for those services.

## Evidence and implementation notes

See [step-4 verification](step4/README.md) for offline, live-provider and Docker
results, including rejected intermediate attempts. Mocked planners verify state,
approval, resume and stopping contracts; they do not prove model decision quality.
The live smoke harness explicitly supplies trusted approvals after checking the
bounded actions and restarts at the apply review to test durable continuation.
This is automated acceptance, not an independent human usability evaluation.

The packaging configuration explicitly includes only `agent` packages. This
prevents editable installation from discovering the ignored `work/` pilot tree.
Dependency versions are retained in `requirements-baseline.txt`.

Design references: [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts),
[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence),
and [Groq structured outputs](https://console.groq.com/docs/structured-outputs).


## Conversational configuration editing

Chat renders readable consent prompts, findings and file diffs. `/debug` exposes
raw state on demand. The last three user/assistant exchanges accompany follow-ups;
`/resume ID` restores that request's saved context. Changing repositories clears
conversation context. History is never an execution approval.

`read_file` and `patch_file` support existing root configuration files: package.json,
package-lock.json, Dockerfile, Compose YAML files, .dockerignore, .nvmrc,
.node-version, requirements.txt and pyproject.toml. This is configuration editing,
not arbitrary source editing or a shell. Files must be regular text under 256 KiB;
each old/new fragment is at most 16,000 characters. A patch replaces one exact
match, validates JSON syntax for JSON files and requires a displayed diff approval.
Symlinked targets, hard-linked writes and detected secrets are refused. Writes use
a project lock, a fresh content check and atomic replacement. Other editors are
not locked. Changes remain uncommitted. Larger file content can exceed the model
context bound; this version does not provide paginated file reading.

A missing engines.node declaration is a setup-policy limitation, not proof that
an application cannot run. Dependency engine constraints do not establish the
project's intended support policy. Edits should explain the distinction and keep
root package-lock metadata consistent. Each file is reviewed independently;
multi-file edits are not an atomic transaction.

Verification: offline regression coverage includes conversation follow-ups,
readable reviews, patch approval/decline/staleness/restart and internal dependency
symlinks. Two Groq action-selection checks verified read_file and a contextual
patch_file selection. These do not establish end-to-end application runtime success.


Current verification: 252 offline tests passed (`work/chat-edit/offline.json`);
two live Groq selections passed (`work/chat-edit/live.json`). An initial test
harness invocation from stdin failed before transport startup; the corrected
file-backed harness performed the two live checks. The actual AgenticMarketplace
application fingerprint passed with installed dependencies and build output
present, taking 149.4 seconds. Full Docker reviews repeat fingerprint checks and
can therefore be slow on large trees; scoped file edits do not scan that tree.
No changes or Docker runtime tests were performed on that application in this pass.
