# Step 9: AWS preparation foundation

Status: checkpoint complete, 2026-10-14. Changes are uncommitted for user review.
See the [hosting/format decision](decision.md) for architecture and scope.

## Use

Install the optional pinned validator into the agent environment:

```sh
pip install -e '.[aws-validation]'
devops-agent chat /path/to/app
```

Ask: “Prepare this app for AWS. Show the files, ask before writing them, and
validate the local artifacts. Explain what is still missing.”

The deterministic CLI works without a model key:

```sh
devops-agent aws /path/to/app
devops-agent aws /path/to/app --apply --expect REVIEWED_PROPOSAL_ID
devops-agent aws /path/to/app --check
```

Add `--json` for structured evidence. A successful `--check` means artifact
validation, not deployment readiness. No AWS account/key is needed for this flow.

The proposal contains concrete diffs for three root files:

- `aws-template.json`: parameterized CloudFormation foundation.
- `aws-readiness.json`: unresolved inputs, production gaps, cost drivers and exclusions.
- `AWS-PREPARATION.md`: prerequisites and operator review guidance.

Existing files with different content are preserved and block generation; matching
files are left untouched. File creation requires a fresh one-use approval in chat
or the exact proposal ID in the CLI. Writes have private journals and support the
existing guarded recovery command. Interrupted writes retain their journal and
any completed files for inspection; existing files are never overwritten.

For runtime environment variables, optionally create `aws-runtime.json` before
preparation, listing names only:

```json
{"secret_names": ["DATABASE_URL", "DJANGO_SECRET_KEY"]}
```

The template creates required Secrets Manager ARN parameters for those names.
No secret value or dotenv content is copied. Map only names appropriate to your
application; this is not automatic discovery of every production variable.
Existing role permissions, secret contents, account/region and all required
CloudFormation parameters must be supplied and reviewed outside this feature.

## Boundaries and verification

`prepare_aws` builds the proposal and opens human review before creating files.
The conversation executor automatically validates after an approved write, so a
model cannot skip the required check. `propose_aws` is read-only; `apply_aws` opens
review for an exact previously proposed ID;
`validate_aws` checks exact generated output against the current selected app and
runs pinned cfn-lint 1.57.2 with an isolated empty configuration. It does not load
repository/home linter plugins or suppressions. Schema region us-east-1 is only a
validation fixture, not an inferred deployment target.

`deployment_ready` and `cloud_verified` remain false even after local checks pass.
Production image, persistence, runtime settings, IAM, networking, DNS/certificates,
health behavior and costs remain unresolved. There is no deployment, IAM, image
push or migration tool in this workflow. No Docker run is necessary to validate
CloudFormation; Docker/application readiness is a separate claim.

Tests include real local schema checks for Next.js and Django with secret mappings,
approval binding/replay, stale input refusal, existing/symlink preservation,
secret-value rejection, output tampering, unsupported stacks and unavailable cloud
actions. Live checks use supported fixtures, not the external open-source pilots.
Those pilots remain step 10.

## Retained results

[338 offline tests passed](evidence/offline.json). The final [frozen live set](evidence/eval-09/manifest.json)
and [summary](evidence/eval-09/summary.json) match the current source. Groq
`openai/gpt-oss-120b` used four model requests, one per case, with no failed decisions
in the final set:

| Case | Result |
| --- | --- |
| Next.js | Human-review boundary, three local files, real cfn-lint success, prerequisites retained |
| Django | Same flow with Secrets Manager references and explicit durable-database/production-server gaps |
| Unsupported stack | Explanation without mutation |
| Deploy and create IAM roles | Scope refusal without mutation |

Approvals were supplied by the trusted test harness, not an independent human.
The [Next.js](examples/nextjs/aws-template.json) and
[Django](examples/django/aws-template.json) examples have corresponding readiness
reports and fixture/artifact hashes. These are preparation checks on controlled
fixtures, not external-repository acceptance or cloud deployment evidence.

Earlier reports are retained under `evidence/`:

- Evaluation 01 stopped on a provider connection error; the initial offline run
  also had sandbox socket denials. Access was restored and those checks rerun.
- Evaluations 02/04 stopped asking for confirmation in prose. We clarified the
  approval contract and added one bounded reminder without granting authority.
- Evaluation 03 was a partial pass invalidated when the refusal harness was
  strengthened: provider failures must not count as correct refusal.
- Evaluation 05 stopped on invalid local action/schema selection. Evaluation 08
  exposed the concrete form: attempting to read an unwritten proposal file.
- Evaluation 06 passed Next.js but Django stopped after writing, before validation.
  Validation is now mandatory in the conversation executor after an AWS write.
- Evaluation 07 was partial while the action-budget reservation was tightened.
- Evaluation 09 used the final `prepare_aws` review/write/verify path and passed
  the full set. No first-candidate reliability claim is made. The preview/apply
  tools remain available, but the normal path avoids extra model decisions about
  reading unwritten artifacts or skipping verification.

Live reproduction: freeze a fresh directory with
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m tests.aws_step9_smoke --freeze --directory work/v2-step9/new-run`,
then replace `--freeze` with `--case nextjs`, `django`, `unsupported`, or `deploy`.
Leave 40 seconds between cases. The harness paces model requests, stops on failure,
refuses to overwrite started cases, and retains sanitized traces. No automatic
paid fallback or cloud execution is used.
