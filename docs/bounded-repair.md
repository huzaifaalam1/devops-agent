# Bounded repair — step 8

`repair` adds a small deterministic diagnose → propose → approve → apply →
validate flow. Each approval allows **one** repair and one runtime validation.
There is no unrestricted executor, model-generated command, or automatic chain
of alternative fixes.

## Initial catalog

| Repair | Required evidence and scope | Effect |
| --- | --- | --- |
| Host port | A failed runtime session with a port-conflict diagnosis; the original port is still occupied; exact agent-generated Dockerfile and Compose layout | Change only the loopback published port in `docker-compose.yml` to the explicit available `--host-port`. Container port and existing owner stay unchanged. |
| Readiness path | A failed runtime session whose HTTP evidence is 401/403; an existing unauthenticated route supplied with `--health-path` | Retry validation with that route. No files or authentication settings change. Future runs must select the path explicitly. |

Missing credentials, unknown failures, package installation problems, custom
Compose edits and cleanup failures remain manual. The command does not invent
secret values, delete caches, stop port owners, disable authentication, or repair
application code. A matching diagnosis alone is never permission to change files.

## Review and approve

```sh
devops-agent validate /path/to/app --run
# Use the failed runtime session ID printed above:
devops-agent repair /path/to/app --session SESSION_ID --host-port 3001
# Review the diff, impact, verification and proposal ID, then:
devops-agent repair /path/to/app --session SESSION_ID --host-port 3001 --apply --expect PROPOSAL_ID

# For a 401/403 failure instead:
devops-agent repair /path/to/app --session SESSION_ID --health-path /health
# Approve with the same arguments plus --apply --expect PROPOSAL_ID.
```

`--json` returns the full sanitized proposal or execution result. Preview does
not edit files or run Docker. It reads the private validation session and current
repository and checks local port availability for a port proposal. Applying
requires an exact reviewed ID; changed inputs, occupied replacement ports,
tampered proposals and concurrent agent actions are refused before edits. If
Docker has not released the previous endpoint port yet, preview asks you to
retry after release; no repair attempt is consumed.

The source must be a failed runtime validation for this exact repository, with
successful/no-needed cleanup and a recorded repair context. Older sessions lack
that context; run `validate --run` again. The first-release eligibility gate still
applies. Existing Git edits to target files remain protected: preserve/reconcile
them before applying. The repair never commits or resets work.

## Bounds and repeat protection

The validation attempt has a 300-second execution budget, a 90-second readiness
budget within it, and the validator's separate bounded cleanup budget. Successful
environments are stopped after verification. Repair success means the requested
service/HTTP checks and cleanup passed; it does not mean the app remains running.

A durable attempt key combines project identity, the input fingerprint and repair
kind. Once an attempt is recorded, unchanged inputs cannot receive that repair
again—even under a new failed validation session or a different replacement port
or health path. There is no force/retry-count flag. Stop and investigate failures;
reconcile the cause before creating new evidence. Deliberately changing source
inputs establishes a different state, not proof that the old cause is resolved.

Fingerprints include regular source/configuration files, bounded to 2,000 files
and 32 MiB, excluding `.git`, dependency trees, build/cache directories and
`work/`. Linked or unreadable inputs and over-limit projects cannot be repaired
automatically. Fingerprints are stale-state guards, not signatures or a sandbox
against a malicious local writer. Use the same private journal storage to retain
attempt history; deleting or changing that storage discards those records.

## Recovery and escalation

A project lock spans apply and validation. Before writes, the session records
approval, proposal ID and exact pre-edit bytes using step 7's private journal.
The runtime attempt has its own session and structured evidence.

On success, a host-port edit remains. `history` shows the repair session;
`recover PATH REPAIR_SESSION_ID` previews reversal and `--apply` performs it
only if the edited file still matches the repair output.

The full replacement is staged and flushed before an atomic file swap, so a
failed staging write leaves the original intact. On failure or cancellation,
the single file edit is reverted when its current
hash still matches the repair's output. A concurrent user edit or a partial write
that cannot be attributed safely is preserved and reported as
`manual_recovery_required`; snapshots remain private. Path-only retries have no
file changes to undo. Unsuccessful results include the new diagnosis, validation
and cleanup evidence, rollback state and a manual next action. No second repair
is attempted. A journal failure is a failure, not a reported repair success.

## Verification

`tests/test_repair.py` covers preview, required approval, proposal tampering,
changed inputs, guarded rollback, cancellation, preservation of concurrent edits,
repeat refusal across validation sessions, eligibility/scope exclusions, route
selection, CLI behavior and redacted evidence. The opt-in
`tests/docker_repair_smoke.py` exercises both repair kinds against a disposable
Next.js development fixture; it requires a working Docker engine, at least 8 GiB
free, and network/cache access for the generated build. It never stops an
unrelated workload or globally prunes Docker state.


The complete offline suite has 138 passing checks. The real Docker smoke passed
both approved repairs against Next.js, preserved the original port owner and
verified that all validation containers were removed. Evidence is saved in
ignored `work/step8-docker.json`. These checks cover the supported development
fixture and bounded repair catalog, not production deployment or broad repair
coverage.
