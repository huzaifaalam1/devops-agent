# V2 step 10 — combined acceptance

Status: implementation and final engineering checks complete on October 15, 2026.
Ready for user review and commit; release acceptance/tagging remain user decisions.

The implementation baseline is `9de8ee48f78c026c1e95d2d345eb8b66619079ec`.
The user committed step 9 before this work. Step 10 leaves its changes uncommitted.

## External pilots

The harness `tests/step10_external.py` takes committed Git archives into temporary
folders. It never edits the source checkouts or copies their installed dependencies,
local secrets or untracked databases. A manifest freezes upstream revision, agent
and test hashes, request and success rules before model calls. Every attempt is
retained separately. Reviews are supplied by the test harness after validating
allowed action types; this is not an independent human UX review.

- [Django Hello World](https://github.com/django-ve/django-helloworld): standalone
  public Django/pip app with a meaningful `Hello, world!` root response. The isolated
  copy declares Python 3.11 from upstream's Dockerfile and preserves that Dockerfile
  as `Dockerfile.upstream.txt`, allowing reviewed generated setup without its
  automatic migrations. Requirements, settings and application code are unchanged.
  This is an **assisted pilot**, not autonomous support for unchanged upstream.
- [Docker Next.js sample](https://github.com/kristiyan-velkov/docker-nextjs-sample):
  uses upstream Dockerfile.dev and lockfiles with the previously reviewed
  single-service `compose.pilot.yaml`. This excludes upstream deployment variants,
  fixed names and sync configuration. Expected page content includes both
  `Next.js Resources` and `Docker Resources`. This is also an **assisted pilot**.
- Existing Docker-Django-Vue-Postgres remains outside the single-app default. Its
  backend needs explicit dependency/runtime/settings preparation; it is not counted
  as a successful whole-repository runtime pilot.

Both positive cases require a real model-selected workflow, real Docker build and
startup, independent HTTP content, unchanged upstream application files, reviewed
stop, removal of owned test resources and preservation of unrelated running containers.

## Reproduction

Each output directory is single-use. Freeze both cases before running either.
Use `PYTHONDONTWRITEBYTECODE=1` throughout. Requires configured Groq credentials,
Docker, free Django port 8000 and at least 8 GiB free disk. No cloud credentials.

```sh
.venv/bin/python -m tests.step10_external --case django --directory work/v2-step10/external-new --freeze
.venv/bin/python -m tests.step10_external --case nextjs --directory work/v2-step10/external-new --freeze
.venv/bin/python -m tests.step10_external --case django --directory work/v2-step10/external-new
.venv/bin/python -m tests.step10_external --case nextjs --directory work/v2-step10/external-new
```

The established `tests.step8_eval` runner supplies five current-candidate live
regressions (Next.js, Django, disposable PostgreSQL, bounded recovery, unsupported
stop). `tests.aws_step9_smoke` supplies four artifact/refusal cases. These are
established fixtures, not additional external repositories. They use 35-second
request spacing; run cases sequentially with time between cases. A 429 is retained
as a failed attempt, without automatic retries or paid fallback.

The offline suite is `tests.run_baseline`. Its `release_ready=false` is intentional:
unit tests alone cannot certify the live release gates.

## Release boundaries

V2 supports bounded single-app Next.js/npm and Django/pip local development,
explicitly disposable generated PostgreSQL, and local ECS Fargate/CloudFormation
preparation. It does not promise arbitrary stacks, whole multi-app repositories,
existing database adoption/migrations, production readiness, cloud deployment,
GitHub Actions or automatic IAM changes. AWS schema validation proves local
artifact structure only; account resources and production image behavior remain
unverified. No automatic git commit, push, tag or release publication.

## Problems found and fixed during acceptance

1. The external Next.js pilot stopped asking for Node/package-manager declarations
   even though the request explicitly selected supported existing-setup validation.
   A prompt-only change still failed. Inspection now exposes per-Compose
   `runtime_options`, computed from the **same policy function** used by the CLI
   validator. These are reviewable candidates, not claims of runtime readiness.
   Unsupported frameworks, application selection, database boundaries and safety
   checks remain blockers. No runtime permissions were broadened.
2. A PostgreSQL live case attempted `prepare_database` before Docker files existed,
   then repeated that failed action. Inspection now retains service facts and
   supplies the ordered prerequisites for eligible apps without setup. Database
   preparation also refuses at review time when generated Compose is missing.
   Files and migration execution still need separate approvals.

Final candidate prompt version: `loop-action-v20`. Five new offline tests cover
shared deferral policy, selected-mode evidence, retained unsupported/database gates,
and missing database-setup prerequisites. The full suite passes **343 tests**.

## Attempts retained

| Candidate/set | Outcome |
| --- | --- |
| v16 / external-01 | Django passed; Next.js asked for already-resolved/template-only prerequisites. |
| v16 / combined-01 | Next.js passed. Remaining queued cases rejected changed source before provider calls; invalidated, not runtime failures. |
| v17 / external-02 | Prompt-only fix still asked for unnecessary declarations. Full-set sequence stopped. |
| v18 / external-03 | Both external pilots passed with independent HTTP and cleanup. |
| v18 / combined-03 | Next.js and SQLite Django passed; PostgreSQL skipped setup prerequisites and stopped after bounded failure. Remaining cases not run. |
| v19 / set-04 | PostgreSQL passed; external Next.js still asked for generation-only declarations. This motivated explicitly scoping generation blockers separately in the planner summary. |
| v20 / set-05 | External Next.js passed. External Django repeated proposal once, then stopped on a provider connection error before applying files. Remaining cases not run. |
| v20 / set-06 | All 11 cases passed on the same frozen candidate, 22 model calls, one duplicate proposal corrected without repeated mutation. |

The initial cancellation harness invocation lacked its test-module import path;
no Docker operation started. With `PYTHONPATH=.` it performed real SIGINT/cleanup
successfully. Reproduction: from the repo root,
`PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 .venv/bin/python docs/v2/step10/cancellation-check.py`.
This check uses a disposable 503 Django fixture and signals only the child process
it created, after observing its own running container.


## Final verification — October 15, 2026

[Machine-readable summary](evidence/final-summary.json) and
[gate-to-evidence map](coverage.md). All final manifests were checked against the
current agent/test hashes after execution. Earlier partial passes do not substitute
for the final complete set.

| Final case | Model calls | Corrected failed selections | Result |
| --- | ---: | ---: | --- |
| [external-06/nextjs](evidence/external-06/nextjs.json) | 1 | 0 | verified / pass |
| [external-06/django](evidence/external-06/django.json) | 3 | 0 | verified / pass |
| [combined-06/nextjs](evidence/combined-06/nextjs.json) | 3 | 0 | verified / pass |
| [combined-06/django](evidence/combined-06/django.json) | 3 | 0 | verified / pass |
| [combined-06/postgres](evidence/combined-06/postgres.json) | 5 | 1 | verified / pass |
| [combined-06/recovery](evidence/combined-06/recovery.json) | 2 | 0 | verified / pass |
| [combined-06/unsupported](evidence/combined-06/unsupported.json) | 1 | 0 | finished / pass |
| [aws-06/nextjs](evidence/aws-06/nextjs.json) | 1 | 0 | prepared / pass |
| [aws-06/django](evidence/aws-06/django.json) | 1 | 0 | prepared / pass |
| [aws-06/unsupported](evidence/aws-06/unsupported.json) | 1 | 0 | finished / pass |
| [aws-06/deploy](evidence/aws-06/deploy.json) | 1 | 0 | finished / pass |

- **343/343 offline tests** passed; no skips, expected failures or unexpected
  successes. [Offline evidence](evidence/offline-v20.json).
- **11/11 final live cases** passed with **22 model calls**. The PostgreSQL planner
  repeated a proposal once; bounded feedback corrected it without re-execution.
  This is not a claim of perfect first-choice reliability.
- [Real SIGINT cancellation](evidence/cancellation.json) passed on the final
  candidate, with owned-container cleanup and unrelated-container preservation.
- External checkouts remained clean. Both external pilots were assisted exactly
  as described above; application/dependency source hashes were preserved.
- Every final owned runtime was cleaned. The pre-existing
  `bio5membertrackfields_database_1` container remained running.
- [Environment](evidence/environment.json): macOS, Python 3.12.14, Docker 29.8.0,
  Compose 5.5.1, LangGraph 1.2.14, checkpoint-sqlite 3.1.1, cfn-lint 1.57.2.
  Provider/model: Groq `openai/gpt-oss-120b`. Compose 2 and other hosts/models
  are not newly certified by these runs.
- No AWS provisioning, deployment, IAM mutation, git commit, push or tag occurred.

The implementing assistant reviewed the reports. The test harness supplied
mutation reviews; neither is an independent human acceptance review. The remaining
release gate is the user's review of these final action/evidence summaries.

Suggested commit: `Complete V2 acceptance and clarify runtime setup prerequisites`.
