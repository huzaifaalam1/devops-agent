# Interactive terminal preview — step 2

Historical checkpoint: this shell is now selected with `chat --offline`. The
default chat uses the [step-4 persistent agent loop](agent-loop.md).

```sh
devops-agent chat --offline
# Or select the application directory upfront:
devops-agent chat --offline /path/to/app
```

With no path, enter an explicit application directory. Empty or invalid paths do
not silently select the current directory. No API key is needed. This checkpoint
is a deterministic, read-only conversation shell, not the model execution loop
planned for steps 3–4. It never calls Docker or a provider, writes app files,
saves chat history, or resumes previous sessions.

Example conversation:

```text
Application directory (or /exit)> /path/to/app
You> inspect this repo
... generation eligibility, source evidence and blockers ...
You> run this repo locally
... next steps; execution is not connected yet ...
You> /status
You> /cancel
You> /exit
```

Commands: `/help`, `/inspect`, `/status`, `/cancel`, `/repo PATH`, `/exit`.
`exit`/`quit` also leave; `cancel`/`stop` clear the current request. Ctrl-C and EOF
end the session, including interruption during inspection. Inspection is
synchronous; Ctrl-C interrupts while it is in progress. Successful repository
switching clears previous findings and intent. A failed selection preserves the
prior repository. Inspection rereads files; `/status` describes the last inspection
and does not claim it is fresh readiness.

Recognized requests include inspection, blocker explanation and local setup
planning. Other requests receive a clarification instead of invented answers.
AWS requests explain future scope. No shell command is available. Repository
content is passed through existing static inspection; output uses redaction and
plain-text rendering. Do not paste credentials: terminal input is visible as typed.

## Verification and boundary

`tests/test_session.py` covers path selection, read-only CLI conversations,
follow-ups, cancellation, switching, unknown commands, cloud refusal, redaction,
stale-result removal, EOF and interruption. A subprocess CLI conversation against
the adapted next-learn pilot exercises setup, status, cancel and exit. PTY startup
was checked, but automated PTY input was blocked by the development environment's
approval policy. These checks verify the terminal shell, not model behavior or
execution. V1 commands remain available; permissions and the agent loop follow.

Checkpoint result: **207 offline tests passed**, including nine new session tests.
The first full-suite attempt could not bind loopback sockets under the sandbox;
after network permission was granted, the complete suite passed. Evidence remains
in ignored `work/v2-step2/offline.json` and `conversation.txt`. CLI help,
documentation links and `git diff --check` also passed. No model requests or Docker
runs were necessary for this read-only checkpoint.
