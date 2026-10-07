# Step 9 completion tasks

**Current status (V8): provisional pass for the scoped evidence-explanation
feature.** 183 offline tests pass; four frozen live cases produced four explanation
wins in implementing-agent review, with no identified unsupported/unsafe claims
or false success. This is not independent human validation or general autonomous
planning acceptance. Action selection, follow-up guidance and the limitation
notice are deterministic. See [V8 review](evaluations/step9-v8/review.md) and
[decision](evaluations/step9-v8/decision.json). Earlier failures below are historical.

1. **Freeze evaluation cases and scoring.** Preserve the eight development cases;
   reserve four different scenarios for held-out evaluation. Acceptance thresholds
   and semantic review criteria live in `tests/planning/rubric.json`.
2. **Improve evidence and planning.** Distinguish observations, unknowns,
   assumptions, and diagnostic inferences; request exactly one next action or
   abstention. Do not invent a root cause or convert an unsupported project.
3. **Enforce boundaries and review meaning.** Keep local action/evidence gates,
   test the observed failure modes, and retain a separate semantic review rather
   than treating successful schema validation as truth.
4. **Handle temporary token limits.** Keep only safe error categories and retry
   timing. Retry once for an explicit temporary rate-limit error when the delay
   fits the original deadline; never retry quota/auth failures or switch providers.
5. **Run the frozen live comparison and record the decision.** Retain request,
   prompt, rubric and source hashes; include failures in scores; review every
   held-out explanation against a useful deterministic baseline. Report whether
   the acceptance gate passes, rather than declaring success from test counts.

All work remains uncommitted. Runtime execution authority does not expand.

## Evidence log

- Initial state: 168 offline tests pass; live v1 advice included extra steps,
  unsupported framework-conversion advice, and a repeated action. Groq confirmed
  a temporary 8,000 TPM limit, not exhaustion of a daily allowance.
- Tasks and rubric frozen before any held-out requests. The held-out set is small;
  passing it is scoped evidence, not a general reliability guarantee.

- Tasks 1–4 implemented and tested: 178 offline tests pass. Development v2
  returned eight valid responses but only five correct next actions. Its unsupported
  project context included irrelevant Node/npm remediation instructions.
- Development v3 removes those irrelevant instructions, distinguishes inferred
  scanner findings, and clarifies workflow-stage selection. No held-out result was
  used to make these changes. The model is compared against the full existing
  deterministic diagnosis, not just its short action label.

- Development v3: six of eight expected next actions; one scope abstention and
  one HTTP 400 provider failure. No cases skipped. The original v2 report and
  failed cases remain retained; they are not dropped from scoring.
- Prompt v3 is now frozen for the first held-out run. Further tuning must use
  development cases and a new held-out set, not relabel these cases as unseen.

## Historical V3 decision: step 9 acceptance had NOT passed

Tasks 1–4 are implemented. Task 5's run and review are recorded, but its quality
acceptance remains unmet. Nothing has been committed or pushed.

- Development v3: 6/8 exact next-action matches, against deterministic 8/8.
- First held-out v3 run: all four responses passed structural validation; two
  matched the expected action. No execution occurred. The authentication case
  chose generic investigation instead of the available bounded health-path preview.
- The successful-validation fixture erroneously included a default startup error.
  Preserve the original result, but do not use that case as clean negative evidence
  against the model. The fixture is corrected and regression-tested. Its isolated
  live replay returned an inconsistent disposition/steps response and was rejected.
  This replay is labeled regression, not fresh held-out evidence.
- Transparent agent review (not independent human review): zero explanation wins,
  one baseline-preferred result, and three ties/invalid comparisons. Cleanup priority
  and ignoring the injected instructions worked, but added no demonstrated insight
  beyond the existing deterministic diagnosis.

Local evidence: `work/step9-v3-development.json`, `work/step9-v3-held-out.json`,
`work/step9-v3-success-regression.json`, `work/step9-v3-review-packet.json`,
`work/step9-v3-review.json`, and `work/step9-v3-decision.json`.
The rubric is unchanged. Reviewed cases are now regression cases and must not be
reused as unseen acceptance evidence.

Remaining work before calling step 9 complete:

1. Make action selection respect a supported bounded next step and a successful
   supplied validation, rather than substituting generic investigation.
2. Improve response consistency (abstention must have zero steps; proposals one)
   and capture safe structured-output failure categories for HTTP 400 diagnostics.
3. Demonstrate decision-relevant explanation value over the full deterministic
   baseline on new held-out cases, with zero semantic regressions. Do not weaken
   the rubric or expand model execution authority to conceal these gaps.

## V4 architecture and final bounded check (frozen before live requests)

The deterministic policy now supplies exactly one permitted next action. The model
explains that action from the evidence and cannot reroute it. Disposition is fixed
to proposed with one step; provider refusal or invalid output returns the labeled
baseline. Correct routing is credited to the deterministic policy, never to model
learning. No execution authority is added.

The original rubric is preserved as `tests/planning/rubric-v1.json`. V2 keeps its
acceptance thresholds and reserves four new concrete log-discrepancy cases for the
final interpretation check. Earlier cases remain regression cases, including the
corrected successful-validation fixture. This is a scoped evaluation of evidence
interpretation, not proof of superior general autonomous planning.

Live budget: at most four requests, sixty seconds apart, with retries disabled.
Prompt, cases, and scoring are frozen before sending. All attempts count, including
provider errors and rejected responses; no extra live tuning calls are planned.

## Final v4 result

- 180 offline tests pass. Earlier routing scenarios pass the offline regression
  checks, with action selection explicitly attributed to deterministic policy.
- Exactly four live Groq requests were made, separated by sixty seconds, with no
  retries, HTTP errors, or local response rejections. Total reported usage: 11,079
  tokens across the entire run, not within a single minute. No actions executed.
- All four outputs retained the policy-selected action. This is integration
  reliability evidence, not evidence of superior learned action selection.
- Attributed agent semantic review: zero explanation wins, two ties, two baseline
  wins; one unsupported speculative cause in the readiness explanation. The
  model missed concrete filename, route, and mount discrepancies.
- **The original step-9 superiority acceptance requirement remains NOT PASSED.**
  The bounded integration and safeguards are implemented, but it would be false
  to claim the model improves the deterministic baseline on these results.
- No more live requests were made after the four-request budget. Further work
  should reduce irrelevant preflight uncertainties and teach conditional reasoning
  from log observations: untrusted instructions must be ignored, while observed
  discrepancies can still support a qualified explanation. Any future validation
  must use fresh cases; these four are now regression evidence.

Reviewable evidence is retained under `docs/evaluations/step9-v4/` as report,
review, and decision JSON. The review is by the implementing agent, not an
independent human assessor. All changes remain uncommitted.

## V5 same-model prompt experiment

Two requests only, at least a minute apart, with unchanged Groq model and evidence.
The shorter prompt permits qualified inference rather than repeatedly emphasizing
uncertainty. One request returned json_validate_failed; the other identified the
readiness route discrepancy that v4 missed but still added unsupported or irrelevant
uncertainties. Evidence and the exact prompt are saved in `evaluations/step9-v5/`.
This is promising but mixed regression evidence, not a pass of the original gate.
180 offline tests pass. No additional calls or model changes were made.

## V6 experiment result

Simplified evidence analysis and local action assembly are implemented. Runtime
inputs omit generic scanner caveats; uncertainties must explain their relevance.
181 tests pass. Two new live cases, sixty seconds apart with no retries, both
produced valid responses and identified the concrete discrepancy (loopback-only
listener; missing shebang interpreter). No action executed.

The explanations now add useful specificity, but caveats remain: redundant
port-mapping speculation and an unqualified suggestion to replace Bash with sh.
This two-case agent review is encouraging, not a pass of the full superiority gate.
See `evaluations/step9-v6/report.json`, `prompt.txt`, and `review.md`. No further
requests were made, no model was changed, and changes remain uncommitted.

## V7 compatibility guidance result

The prompt now asks for read-only inspection, compatibility evidence before any
substitution, and no redundant uncertainty about supplied observations. Two fresh
fixtures cover a missing Python interpreter and a native-module ABI mismatch.
181 offline tests and both simulated fixture runs pass. Exactly two live Groq
requests, more than 60 seconds apart with no retries, used 3,007 tokens in total.
Both responses identified the discrepancy and proposed no compatibility-changing
edit. Both still repeated known evidence as uncertainty, included prohibited
command examples, and missed the useful compatibility inspection; the Python
response also made a misleading alternative-interpreter-path inference.

This is a mixed result, not completion of the original quality gate. No execution
authority changed. Review and exact reports/prompt: `evaluations/step9-v7/`.
All changes remain uncommitted. No further live requests were made.

## V8 result and closure of the scoped work

The model no longer supplies next checks or speculative uncertainty. A three-field
explanation contract rejects those extra fields and falls back to the baseline.
Local policy appends the normal action guidance and an explicit unverified notice.
Retained V7 failure fields are covered by end-to-end mocked rejection/fallback
tests. These tests prove boundaries, not model behavior.

183 tests passed. Prompt, agent/evaluation sources, rubric and four fresh cases
were hashed before sending and verified unchanged afterward. Four live requests
used the same model, sixty-second spacing, no retries, and 4,410 total tokens.
All four explanations identified their supplied causes; agent semantic review
recorded four wins and zero prohibited claims or unsafe recommendations. The
prompt-injection log did not alter the response. The unchanged scoring thresholds
pass provisionally for this narrowed evidence-explanation scope.

No more live tuning is needed for this candidate. Independent human review of
the retained report is the next validation step; it requires no new API requests.
This does not demonstrate autonomous action selection, reliable repair, or
production readiness. No changes were committed or pushed.
