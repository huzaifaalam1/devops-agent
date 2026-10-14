# Step 8: diagnosis, reviewed recovery and agent evaluation

Implementation and checkpoint verification complete, 2026-10-14. Changes remain
uncommitted for user review. Baseline: `8cf9727`. AWS preparation is step 9;
external pilots and the combined release gate remain step 10.

## Behavior

- Chat retains bounded failure diagnoses in model observations and checkpoints.
  Pip installation, Python initialization, migration, HTTP and cleanup failures
  have specific evidence and guidance. Unknown causes remain uncertain.
- An occupied port returns control to the user to free the original port. Django
  stays on 8000. Uncertain cleanup stops further automatic work.
- After HTTP 401/403, an existing public readiness route supplied by the user or
  repository evidence can be proposed and separately approved. One verification
  rebuilds a disposable environment from the failed session's journal, then cleans
  it up. It does not require a currently running container. Authentication and
  repository files remain unchanged; future runs must select the health path.
- The persistent repair fence rejects another attempt on unchanged inputs. New
  conversations do not reset it. Generic repair cannot replay PostgreSQL setup.
- Migration failures retain their owned session for inspection and provide a
  structured explanation. They do not automatically retry or reverse migrations.

## Final verification

The [frozen manifest](evidence/eval-04/manifest.json) records source/fixture hashes,
prompt v12, tool schemas, provider/model, limits, requests and success rules before
live evaluation. The final source matches that freeze. Groq `openai/gpt-oss-120b`
used **13 requests** across the final five cases, with no failed actions or 429s.
Previous attempts are retained separately; this is not a first-candidate pass.

| Case | Calls | Verified result |
| --- | ---: | --- |
| Next.js | 3 | Generated setup, real build, independent HTTP 200 and page marker, cleanup; resume before apply |
| Django/SQLite | 3 | HTTP 200 on 8000, expected page, unchanged host database, runtime isolation, cleanup |
| Django/PostgreSQL | 4 | Separate migration approval, migrations, ORM operations, independent page, reviewed stop and cleanup |
| Recovery | 2 | Real 401, reviewed `/health` retry with HTTP 200, unchanged Compose, cleanup, second attempt refused |
| Unsupported stack | 1 | Correct refusal with no mutation or Docker execution |

The [final summary](evidence/eval-04/summary.json) and full case reports are retained
in the same directory. [All 320 offline tests passed](evidence/offline.json).
The supplemental [real port-owner test](evidence/port-owner.json) used a scripted
planner with a real socket on 8000 and Docker preflight. The loop stopped after one
model decision, preserved the listener and Compose, and asked the user to free the
port. It makes no live-model behavior claim. Reproduce from the repository root:
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python docs/v2/step8/port-smoke.py`.

All test-owned runtimes were stopped and cleaned up; unrelated running containers
were preserved. Shared Docker build cache remains. No application-source repair,
authentication bypass, existing-database migration or cloud action was performed.

## Evaluation limits and reproduction

These are five held-out **request phrasings** on established integration fixtures,
not an unseen-repository benchmark. The recovery harness injects the original
failure and supplies the known public route. It verifies model-directed recovery,
not autonomous health-route discovery. Harness wrappers provide the frozen request,
request pacing and scoped approvals; model replies and Docker operations are real.
The implementing agent's review is not independent human validation. The user
should review these action/evidence summaries before the final V2 release claim.

Freeze a fresh output directory with
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m tests.step8_eval --freeze --directory work/v2-step8/new-run`.
Run each case with the same command, replacing `--freeze` with `--case CASE`:
`nextjs`, `django`, `postgres`, `recovery`, `unsupported`. Leave 40 seconds between
cases and ensure 3000/8000 are free. The harness spaces decisions 35 seconds apart,
stops on 429, checks frozen hashes, and refuses to overwrite a started case. It
requires the configured local provider key, Docker and at least 8 GiB free disk.

## Earlier attempts and fixes

- Initial deterministic recovery passed HTTP verification but its replay check
  encountered port-release delay before the attempt fence. The fence now takes
  precedence. The fresh deterministic rerun passed.
- Evaluation 01 reached successful live recovery but the harness expected project
  metadata removed by chat compaction. Cleanup verification now reads the test's
  own private validation journal. This evaluation remains marked failed.
- Evaluation 02 hit recovery preflight port-release delay without making a model
  request; Next.js hit an overstrict harness assertion. The assertion now permits
  `existing_setup=True` only with the explicit generated Compose selection.
  Django, PostgreSQL and refusal passed that earlier run.
- Evaluation 03 exposed the planner's mistaken belief that recovery required a
  running container. Prompt v12 explains the failed-session journal contract.
  That candidate was invalidated. A Next.js case already in flight finished;
  subsequent cases refused mismatched hashes. None count toward final acceptance.
- Evaluation 04 used another fresh frozen prompt set and passed all five cases.

The `evidence/` directory retains sanitized earlier reports and failure logs as
well as the final set. External standalone Django and Next.js pilots remain part
of step 10, so these results do not certify arbitrary repositories.
