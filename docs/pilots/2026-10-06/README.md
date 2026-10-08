# First external-repository pilot — October 6, 2026

Agent revision: `4b56b8e`. Each upstream revision is recorded in `summary.json`.
Four clean checkouts were copied into an ignored pilot workspace, excluding Git
metadata. The Next Learn case uses `basics/learn-starter`, not the monorepo root.
The four-case cohort was recorded before running. Each case received `analyze`,
`dockerize` preview, configuration `validate`, and `validate --run --json`.
No application source was executed; runtime requests stopped at eligibility.

## Results

| Case | Configuration check | Runtime outcome | Main evidence |
|---|---|---|---|
| Next Learn starter | No Compose file | Refused at eligibility | pnpm lockfile, no npm lockfile, `.nvmrc` selects Node 18 |
| Docker Next.js sample, development branch | Passed | Refused at eligibility | npm and pnpm lockfiles, missing package Node engine, multiple Dockerfiles |
| Next.js/Postgres/Prisma template | Passed | Refused at eligibility | Node 20 Dockerfile versus agent Node 22 target, multiple Compose variants, database/environment blockers |
| Django/Vue/Postgres | Failed: missing `.env` | Refused at eligibility | Multiple components and unsupported framework |

Zero of three prospective Next.js candidates were runtime eligible. These are
coverage/eligibility findings, not three failed application builds. There were
four runtime requests, zero starts, zero verified startups and zero claimed
runtime successes. False-success rate is undefined because its denominator is
zero. Time to a working application and repair/recovery rates are also unmeasured.
No model requests were sent; live model quality was not part of this screening.

The first shortlist was insufficiently screened: Next Learn was presented as a
potential npm baseline, but the selected checkout actually uses pnpm and Node 18.
That is a selection error, not evidence that the agent broke a supported npm app.
The unchanged candidate and its failure remain in the results.

## Follow-up priorities

1. **Fix misleading unsupported-stack guidance.** Django component analysis
   recommends npm lockfiles, Node 22 and `next dev`. A correct execution refusal
   does not make these recommendations useful. Suppress stack-specific setup
   advice when the stack is unsupported; retain actual component findings.
2. **Make existing-setup selection usable.** The examples contain multiple
   legitimate Dockerfile/Compose variants. The agent requests a different
   directory instead of accepting an explicit intended configuration. Existing
   Compose also warrants separate eligibility criteria from generated Node 22
   setup. Do not silently relax resource-ownership protections: explicit container
   names and writable mounts in these candidates would need further review.
3. **Reconcile configuration evidence.** The database example passes Compose
   config using defaults, while static analysis reports missing dotenv values.
   Neither result proves connectivity. Distinguish required missing values from
   values supplied by the selected Compose configuration, without exposing them.
4. **Improve redaction precision.** Public example dotenv values cause words in
   repository names and common ports to become `[REDACTED]`. Preserve credential
   protection while testing how useful non-secret context can remain readable.
5. **Add a genuinely eligible external npm/Node 22 case.** Keep this cohort's
   results, then verify lockfile/runtime requirements before adding a new case.
   Do not convert a pnpm repo merely to manufacture a passing baseline. Runtime
   storage planning is also needed: this host had about 6.1 GiB free at screening.

## Preservation and limits

All original Git checkouts remained clean; byte hashes and symlink targets in the
pilot copies matched the selected source trees after testing. No new containers
appeared, and all pre-existing container IDs remained present. No apply, repair,
image build, dependency installation, or cleanup command was issued. This verifies
absence of changes in this refusal-only run, not runtime isolation under load.
Application readiness, database transactions, cancellation, repair and runtime
cleanup still need an eligible pilot run. No claim of step 10 completion is made.

Per-case JSON contains actual CLI results, exit codes and elapsed command time;
`summary.json` records revisions, blockers and aggregate counts. Local paths are
normalized. The ignored `work/pilot-2026-10-06/` retains original outputs, copied
inputs, and the two driver scripts. No upstream application content is vendored
into the report. Nothing has been committed or pushed for this pilot.
