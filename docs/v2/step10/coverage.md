# Acceptance evidence map

Engineering checks passed on October 15, 2026; user acceptance review is pending.
This map identifies the evidence; final outcomes are in the [retained reports](README.md#final-verification--october-15-2026). A unit-test pass is not a live-model behavior claim.

| Gate | Deterministic coverage | Real execution evidence required |
| --- | --- | --- |
| V2-01 | `test_loop`, `test_tools` | Current combined Next.js and external Next.js pilot |
| V2-02 | `test_conversation`, `test_session` | Real SIGINT during owned runtime validation |
| V2-03 | `test_tools.test_invalid_calls_do_not_reach_backend`, `test_loop.test_invalid_tool_never_executes` | Current live action traces; no malformed-action pass inferred from mocks |
| V2-04 | `test_tools.test_output_instructions_and_secrets_are_not_authority`, `test_loop.test_secrets_not_persisted` | Captured boundary payload tests; no arbitrary shell tool exists |
| V2-05 | stale review, interrupted mutation ledger, checkpoint and resume tests | Combined Django pause/reopen before apply; Next.js resume |
| V2-06 | provider failure, repeating action and budget tests | Current live valid-action cases; historical rate-limit failures retained |
| V2-07 | `test_django_project`, `test_django_runtime` | Current combined Django and external standalone Django page |
| V2-08 | Django ambiguity, settings and dependency inspection tests | Correct blocked external mixed-stack inspection; no unsupported runtime claim |
| V2-09 | `test_django_database` | Current PostgreSQL separate migration review, ORM and HTTP checks |
| V2-10 | external target, existing Compose and unowned DB refusal tests | No destructive/external DB execution needed |
| V2-11 | diagnosis and bounded repair tests | Current real 401-to-health recovery; retained step-8 real port-owner check |
| V2-12 | runtime/install/config diagnosis tests | Current real 401 case and retained step-8 failure evidence |
| V2-13 | `test_repair`, `test_safety` rollback/conflict tests | Recovery replay refusal; guarded file apply/recovery in offline integration tests |
| V2-14 | `test_aws_preparation` | Current AWS cases with real local cfn-lint |
| V2-15 | unresolved input/no fabricated values assertions | Current AWS Django/Next.js incomplete readiness reports |
| V2-16 | closed inventory and cloud refusal tests | Current cloud-deploy refusal; no AWS provisioning |
| V2-17 | ownership/redaction/cleanup tests | Current runtime inventory, reviewed stops, SIGINT cleanup |
| V2-18 | Entire `tests.run_baseline` suite | Current generated Next.js and external existing-setup Next.js |

The implementing assistant reviews these artifacts. Final user review is still
required before declaring the release accepted. Compose 5 coverage does not
silently certify Compose 2, and assisted pilots do not prove arbitrary repository
support. There is no production deployment acceptance claim.
