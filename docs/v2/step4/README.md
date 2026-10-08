# Step 4 verification

**Passed within the current Next.js/npm boundary.** The terminal now uses a
bounded LangGraph loop, local SQLite checkpoints and the existing approved tool
registry. Django, migrations, AWS and broad repair remain later milestones.
See [the usage and recovery guide](../agent-loop.md).

## Final candidate

- [Offline suite](final-offline.json): **242 passing tests**, zero expected failures.
  Includes actual SQLite checkpoint/restart tests, concurrent-resume refusal,
  interruption after a temporary filesystem mutation with no replay, completed
  operation reuse, stale approvals, secret checks, request limits, repetition
  refusal, replanning with a changed health path and terminal approval tests.
- [Fresh live Next.js run](typed-runtime-retry.json): configured Groq
  `openai/gpt-oss-120b` selected propose → apply → validate on a new pinned fixture.
  The harness restarted at the apply review and obtained a fresh review before
  continuing. Three model requests selected the actions. Real Docker build and
  readiness passed; an independent GET returned HTTP 200 with
  `devops-agent-baseline-ready`. Scoped containers, network, volumes and generated
  image were cleaned up afterward. The app is no longer running.
- [Live unsupported-stack stop](final-blocked.json): one model request, a specific
  unsupported-framework explanation and no mutation or Docker execution.
- [Installed terminal conversation](cli-conversation.txt): provider decline and
  exit through the actual entry point, without a model request.
- Editable reinstall, `pip check`, CLI help and diff checks passed.
- [Manifest](manifest.json), [prompt](prompt.txt) and [typed schema](action-schema.json)
  retained. Source hashes in both final live cases and the offline report were
  checked against the final agent source.

Live harness approvals are explicitly supplied by test code after inspecting the
bounded action type/proposal. They are not model-issued approvals and are not an
independent human UX review. Offline fault injection proves boundary behavior,
not real model decision quality. These two live scenarios are step-4 acceptance,
not the broader frozen quality set planned for step 8 or a v2 release certification.

## Development attempts retained separately

| Evidence | Outcome |
| --- | --- |
| [First prototype](live-first.json) | Local response validation refused the action before mutation; detailed cause was not retained. |
| [Prototype retry](live-second.json) | Full live startup/restart/page/cleanup passed with the earlier arguments-string contract. |
| [Subsequent prototype run](final-runtime.json) | Model invented Dockerfile/Compose arguments for a zero-argument proposal tool; local validation refused them. |
| [First typed-schema run](typed-runtime.json) | Provider rejected the schema before action selection. |
| [Schema diagnostic request](schema-diagnostic.json) | HTTP 400 identified an empty required-list issue on zero-argument objects. |
| Final typed candidate above | Removed the empty required list while preserving closed objects; real startup and unsupported-stop cases passed. |

The final contract uses a typed action union, not a JSON string containing
arbitrary arguments. The provider constrains each tool's parameter shape and
local validation still independently rejects invalid parameters. No model upgrade
or relaxed execution permission was used to obtain a pass. Earlier reports are
historical attempts, not evidence for the final candidate.

## Reproduce (explicitly sends model requests and runs Docker)

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m tests.run_baseline \
  --output work/v2-step4/offline-repeat.json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m tests.agent_loop_smoke \
  --output work/v2-step4/runtime-repeat.json
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m tests.agent_loop_smoke \
  --case unsupported --output work/v2-step4/blocked-repeat.json
```

The startup case requires free port 3000, Docker and at least 8 GiB host free
space. It uses private per-run Buildx and state directories outside the fixture.
No unrelated workload is stopped; no global pruning occurs. Provider failures
remain failures and all attempts should be retained. The unsupported case is not
a supported-repository runtime pass.
