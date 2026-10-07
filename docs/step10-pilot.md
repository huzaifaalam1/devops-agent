# Step 10: pilot, measure, and expand deliberately

Recovered on October 6, 2026 from the Apple Notes page
“DevOps Agent — Foundation Strengthening Plan” (September 5, 2026).

Original direction: run a pilot on actual user repositories before broadening
framework support. Measure verified startup success, false success, time to first
working application, user interventions, diagnosis accuracy, repair success and
recovery, and unintended changes or disruptions.

## Starting point

The CLI supports scoped Next.js/npm analysis, reviewable Docker setup, staged
validation, evidence-backed diagnosis and two bounded repair kinds. Step 9 adds
an explanation-only model contract; action selection and follow-up guidance stay
deterministic. Its four-case synthetic evaluation passed implementing-agent review,
not independent human review or a real-repository pilot. The 183-test suite and
previous Docker fixtures do not establish reliability on unfamiliar applications.

## Pilot work

1. **Select and freeze the pilot cohort.** Choose three to five actual repositories
   with the owner: a minimal supported app, an existing Compose app, and an app
   with a dependency or configuration complication. Record revisions, dirty state,
   prerequisites and exclusions before running. Report unsupported projects as
   screened out, never as startup successes. Use isolated working copies where
   practical and preserve original work.
2. **Create a run record.** Record revision, environment, commands/approvals,
   timestamps, stages passed, readiness evidence, interventions, diagnosis review,
   repair attempts, rollback and cleanup. Keep secret values out of records.
   Missing prerequisites, failures and timeouts stay visible; do not count only
   completed runs. Retain model latency and token usage when advice is requested.
3. **Run the existing workflow.** Analyze → preview → approve → apply → validate;
   diagnose and use only supported repairs when justified. Use the same starting
   state and success definition for comparisons. Enable model advice separately
   so its explanation can be compared with the deterministic diagnosis; do not
   attribute automatic repair or routing to the model.
4. **Verify independently of the agent's status.** Check the intended application
   response, required dependencies, changed files, owned resources and cleanup.
   Record false success when an agent success claim fails the agreed check.
   Review diagnosis usefulness and correctness with the repository owner. Test
   recovery only within the pilot copy and existing approval boundaries.
5. **Publish a pilot decision.** Report counts with denominators: verified startup
   successes / attempted in-scope runs; false successes / claimed successes;
   repair successes / repair attempts; recoveries / required recoveries. Report
   failed/time-limited runs separately from successful startup durations. Count
   interventions and unintended changes per run. Keep diagnosis review failures
   and unknowns visible. Fix reproducible gaps before adding frameworks or cloud
   deployment. Agree broader release targets before interpreting pilot results.

## Exit evidence

A reproducible report for every selected repository, independently checked
readiness and cleanup, no unexplained unintended changes, and a prioritized list
of observed failures. Any false success or harmful side effect blocks expansion
until investigated and covered by regression checks. A small pilot is directional
product evidence, not a statistical reliability guarantee.

Next input needed: the actual repositories to include, plus their expected endpoint
and any required local configuration. No pilot repositories have been selected or
run yet. Web UI, multi-agent orchestration, broad AWS support and additional
frameworks remain deferred by the original roadmap.
