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
Identical actions on unchanged repository inputs are refused, including redundant
initial inspection. There is no automatic provider retry: a 429 reports an
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
