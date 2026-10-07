# Step 9: evidence-based model planning

The `advise` command sends reviewed, sanitized evidence to the selected provider and returns
unverified hypotheses and proposed actions. It never executes a proposed action,
changes a validation result, grants approval, or claims application readiness.
Existing deterministic commands and repair limits remain the execution boundary.

## Model and setup

The default provider is Groq with `openai/gpt-oss-120b`. It supports strict
structured output and is available under Groq's published free-plan limits.
The `openai/` prefix is the model's name; requests go to Groq, not OpenAI.
Quality relative to GPT-5.2 is not yet measured in this project.

Paste your Groq key into the DevOps Agent repository's Git-ignored `.env`:

```dotenv
DEVOPS_AGENT_PROVIDER=groq
GROQ_API_KEY=your-key-here
DEVOPS_AGENT_MODEL=openai/gpt-oss-120b
```

No automatic provider fallback exists. Missing Groq credentials or a rate limit
never switches to OpenAI. To explicitly use OpenAI, select provider `openai`,
model `gpt-5.2`, and configure `OPENAI_API_KEY` instead.

Groq's published limits for this model, checked September 18, 2026, are 30 requests
per minute, 1,000 per day, 8,000 tokens per minute, and 200,000 tokens per day.
Account limits are authoritative. The often-cited 14,400 requests/day is not a
universal free-tier allowance. Free access depends on your Groq account plan;
this agent neither enables billing nor verifies the account's billing tier.
[Groq rate limits](https://console.groq.com/docs/rate-limits).
[Strict structured output models](https://console.groq.com/docs/structured-outputs).

The model setting is optional: the selected provider supplies its default. The agent reads `.env` next
to its own `pyproject.toml`, regardless of the current directory or target project.
Exported environment variables override file values; `--model` overrides both.
Simple unquoted or quoted single-line values and comments are supported, with no
shell execution or variable interpolation. Preview requires no key. Sending still
requires the reviewed request ID.

```sh
python -m agent.main advise /path/to/app --json
# Review the complete request and copy its id into the following command.
python -m agent.main advise /path/to/app --send --expect REVIEWED_ID --json \
  --input-rate 0 --output-rate 0
```

Use `--session VALIDATION_SESSION_ID` on both commands to include evidence from a
completed `validate --run`. The session must belong to this exact repository and
match its current source fingerprint. Re-preview after edits or changes to the
model, evidence, or output budget. A project lock protects the final recheck and
request. External editors do not honor this lock; the transmitted request is the
reviewed snapshot, not a promise the working tree will remain unchanged.

## Request and result contract

The preview shows the exact request, endpoint, model, baseline, and approval hash.
Only the `request` object is transmitted. It contains bounded structured findings,
blockers, uncertainties, optionally validation and diagnostic summaries, and up to
ten log lines. It excludes full source files, raw commands, private recovery
snapshots, journal history, repository paths, and session IDs. Existing redaction
removes known secrets; it cannot identify every possible secret, so inspect the
preview. Repository text and logs are explicitly treated as untrusted data.

Requests use fixed, allowlisted HTTPS Responses endpoints and strict JSON schema.
OpenAI requests set `store: false`; Groq requests omit this unsupported parameter.
No arbitrary base URL or cross-provider credential reuse is permitted.
[Groq Responses compatibility and limitations](https://console.groq.com/docs/responses-api).
[OpenAI structured output contract](https://developers.openai.com/api/docs/guides/structured-outputs).

Bounds: evidence bundle at most 24,000 bytes; at most two API requests per invocation;
256–4,096 output tokens (default 2,000); 256 KiB response body; 60-second parent
deadline with up to four additional seconds for worker termination. One retry is allowed only for HTTP 429 with explicit `rate_limit_exceeded` and a
provider delay of at most 20 seconds that fits the original deadline. Other errors
are not retried. Redirects, environment proxies, and model tools are disabled. Token limits bound
output, not an exact dollar amount. Optional cost estimates use user-supplied
rates and returned usage; absent usage/rates produces `null`, not zero cost.

Local checks enforce known evidence IDs, available action IDs, distinct actions,
a locally supplied limitation notice, and bounded response shape. Refusals, incomplete output,
tool calls, invented fields, and malformed JSON are rejected. Errors return the
labeled deterministic baseline without executing it. Private journals record
request identifiers, model, outcome, usage, cost estimate, and latency. A journal
write must succeed before sending. Cancellation and final audit failures remain
explicit outcomes.

`success` means a response passed structural checks, **not** that the application
works. `verified` is always false and `actions_executed` always zero. Free-form
hypotheses can still be wrong, including while citing real evidence IDs. Semantic
claim accuracy is unmeasured (`null`); schema validation cannot establish truth.

## Evaluation and acceptance

Offline, no key, no network, no Docker:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m tests.planning_eval \
  --output work/planning-contract.json
PYTHONDONTWRITEBYTECODE=1 python -m tests.run_baseline \
  --output work/step9-tests.json
```

Live evaluation reads the same `.env` and sends up to eight synthetic requests.
It stops on HTTP 401, 403, or a final HTTP 429 and records skipped cases.
Interactive advice can perform the bounded temporary-limit retry described above.
Live evaluations disable retries and send at most one request per selected case.
Requests count toward provider limits. Zero rates below are estimates for an
account you have confirmed is on the free tier, not proof of zero billing:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m tests.planning_eval --live \
  --input-rate 0 --output-rate 0 --output work/planning-live.json
```

Cases cover missing/existing setup, unsupported projects, missing environment
configuration, occupied ports, unknown failures, cleanup failure, and injected
log instructions. Reports retain the exact synthetic evidence, request hash,
prompt version, model, action-match comparison, unnecessary-action counts,
latency, usage, and estimated cost. Offline responses are simulated fixtures and
are never presented as model quality evidence. Live failures remain failures;
fallback actions do not get counted as successful model proposals.

Before expanding authority, run the live comparison and have a reviewer assess
every hypothesis against its cited facts. Record unsupported claims, false
success claims, and whether explanations help choose the right next step. Compare
explanations blind against the deterministic baseline; use a held-out set before
changing the prompt based on these cases. Matching a perfect action baseline is
not outperforming it. The report deliberately leaves `model_outperforms_baseline`
unknown until this quality review exists. Step 9's superiority acceptance criterion
is outstanding until live evidence establishes better usefulness without increased
unsafe actions or false success claims.

## Live verification (September 21, 2026)

Groq credentials and Responses structured output were verified against synthetic
fixtures. The first run produced three structurally accepted plans, one rejected
plan, then HTTP 429. A later isolated missing-environment request was rejected for
an unavailable or repeated action. The full quality gate has not passed: accepted
plans included unnecessary actions, and the unsupported-project response proposed
converting the project to Next.js rather than respecting its existing stack.
No proposed action was executed. Reports are retained locally in
`work/groq-live.json` and `work/groq-live-missing-environment.json`.

The evaluator now spaces Groq cases by 60 seconds by default and supports
`--case missing-environment` to isolate a scenario and `--interval` (0–60 seconds)
to adjust spacing. Spacing does not guarantee the account token limits will not
be reached; HTTP 429 still stops the run. Numeric usage counters remain visible
while credential strings continue to be redacted.

## Frozen step 9 comparison

The five completion tasks are tracked in `step9-completion.md`. Prompt v4 explains one policy-selected next action, distinguishes evidence kinds,
and forbids converting unsupported projects. Both the schema and local validation
require exactly one step and a proposed disposition. Refusals or invalid output
return the deterministic baseline instead of another model-selected action. Semantic
truth is still reviewed separately, not inferred from a valid schema.

```sh
python -m tests.planning_eval --live --split development --output work/development.json
python -m tests.planning_eval --live --split held_out --output work/held-out.json
python -m tests.planning_review work/held-out.json --output work/review-packet.json
# Fill in the packet's review_template and save it as work/review.json.
python -m tests.planning_review work/held-out.json --review work/review.json --output work/decision.json
```

The frozen rubric requires all four held-out cases, exact useful action selection,
zero unnecessary actions or reviewed semantic violations, and at least three
explanation wins without regressions. Failures/skips cannot be removed from the
denominator. Reports bind the source and rubric hashes; reviews bind the complete
report. A/B labels omit provider identity, although response style can still reveal
which answer is model-generated. Agent reviews are explicitly attributed and
provisional; they must not be presented as independent human review. Do not tune on
held-out results and then describe repeats as fresh held-out evidence.


The historical v3 acceptance decision was **not passed**. See `step9-completion.md` for
v3 development/held-out results, the invalid success fixture disclosure, its
corrected regression, and the attributed semantic review. `--split regression`
explicitly labels replays; these cannot satisfy the held-out decision gate.


V4 freezes a fresh four-case interpretation evaluation with the same acceptance
thresholds. Action selection is now deterministic; only explanatory usefulness is
credited to the model. Older held-out cases remain regression cases. See the final
status in `step9-completion.md` before treating the integration as validated.


V4 result: four live requests succeeded and retained the deterministic action;
180 offline tests pass. The attributed semantic review found no explanation wins,
so the original quality acceptance has **not passed**. Inspect the preserved
`evaluations/step9-v4/decision.json`, `review.json`, and `report.json` rather than
interpreting structural success as proof of usefulness. No execution authority
has been expanded.


## V6 evidence-analysis contract

The model now returns only `observed_discrepancy`, `explanation`, `next_check`,
`evidence_ids`, and a nullable `uncertainty`. An uncertainty must contain both
`missing_evidence` and `impact`. Each text is locally bounded to 300 characters.
Action IDs, disposition and steps are absent from the model schema. Local code
assembles the display plan using the single deterministic action; unexpected
fields, invalid references and malformed uncertainty objects are rejected.

When a current validation session is supplied, outbound facts omit generic static
scanner findings, unknowns, assumptions and the generic diagnostic hypothesis.
Eligibility, scope blockers, validation/cleanup/HTTP results, errors and bounded
log observations remain. This prioritizes direct runtime evidence without hiding
scope or cleanup restrictions. Preflight advice retains its scanner context.

The same-model V6 experiment uses two new cases selected before live requests,
with at least 60 seconds between calls and no retries. It is a small experiment,
not a replacement for the frozen step-9 superiority gate or broad safety testing.

## V7 inspection guidance

The prompt requires `next_check` to identify one read-only inspection and what it
would establish. Runtime/interpreter substitutions require compatibility evidence;
already supplied inventories should not become redundant uncertainties. This is
a prompt-level quality constraint, not a semantic guarantee enforced by the JSON
validator. Advice remains unverified and cannot execute changes.

## Current V8 explanation-only contract

V8 supersedes the V6/V7 model-written checks and uncertainties above. The wire
response contains only `observed_discrepancy`, `explanation`, and `evidence_ids`.
The application appends the existing deterministic action guidance and a fixed
notice that the explanation and replacement compatibility are unverified. The
legacy display field `uncertainties` now contains that notice, not model prose;
the CLI labels it `Limit`. Unexpected next-check or uncertainty fields cause
rejection and baseline fallback rather than silent sanitization.

This deliberately narrows the model's job to explaining supplied evidence. It
removes two unreliable output surfaces; it does not semantically validate the
remaining free text. A model can still make unsupported claims or include advice
in its explanation. Offline replay verifies rejection/routing, not model quality.

The V3 rubric preserves the earlier thresholds (at least three explanation wins
out of four and no regressions, unsupported claims, unsafe recommendations or
false success claims). Four fresh cases cover TLS scheme, Unix socket permissions,
relative resource lookup, and proxy path forwarding. A prompt-injection instruction
is included in the resource log. Source, prompt, cases and rubric are frozen before
live requests; calls use the same Groq model, sixty-second spacing, and no retries.
The prior rubric is retained as `tests/planning/rubric-v2.json`.
