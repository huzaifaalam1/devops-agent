# Execution safeguards — step 7

The CLI now applies an explicit action policy, records mutations in private local
journals, protects existing edits, and supports guarded recovery. No autonomous
repair, deletion of unrelated resources, deployment, or arbitrary tool executor
is introduced.

## Authorization and scope

| Action | Authorization | Boundary |
| --- | --- | --- |
| Analyze, proposal preview, config validation, history/recovery preview | Command invocation | Read-only inspection; no app code execution by analysis |
| Apply generated files | `dockerize --apply` (optionally `--expect ID`) | Only the current reviewed proposal's three allowed target files |
| Build images | `validate --build` | Project-local build context, run-specific image tags |
| Start services | `validate --run` | Unique project, local Docker engine, loopback ports, scoped cleanup |
| Preserve successful environment | `--run --keep-running` | Only that validated project; reports a scoped stop command |
| Restore pre-edit files | `recover PATH SESSION_ID --apply` | Matching original root, allowlisted files, unchanged post-apply hashes |
| Destructive/external/infrastructure actions | Not implemented | No generic approval flag or arbitrary command dispatch |

Direct calls to the named apply/build/run APIs carry the same explicit intent as
the corresponding CLI command. These are application policy boundaries, not a
sandbox against arbitrary Python callers or malicious Dockerfiles. Build/run
executes repository/container code and may fetch packages/images. Use trusted
projects: there is no network egress sandbox. Repository text and logs cannot
grant approvals, choose arbitrary host commands, or enable additional actions.

Validation rejects outside build contexts and Dockerfiles, extra build contexts,
SSH/secrets forwarding, cache exporters/importers, entitlements, host namespaces,
extra capabilities, Docker socket injection, and unsupported mount types. Existing
isolation checks still reject writable/external bind mounts and shared resources.
Wildcard published ports become loopback bindings in the temporary validation
configuration; the source Compose file is unchanged. Explicit nonlocal host
bindings are rejected.

## Existing work and recovery

Apply recomputes the proposal and verifies its inputs. In Git repositories,
modified/staged/untracked/ignored existing target files are refused; unrelated
uncommitted files remain untouched. Git inspection disables fsmonitor execution
and inherited repository/index overrides. No commit, stash, reset, or checkout is
performed. Outside Git, existing target bytes are snapshotted before modification.
Symlink and hardlink targets are refused. A per-project advisory lock serializes
agent mutations that use the same journal storage; it does not lock other editors.

```sh
devops-agent dockerize /path/to/app --apply --expect REVIEWED_ID
devops-agent history /path/to/app
devops-agent recover /path/to/app SESSION_ID
devops-agent recover /path/to/app SESSION_ID --apply
```

Apply returns a session ID and recovery preview command. Recovery lists removals
of created files and restoration of updated files; it does not print backup
contents. All targets are checked before any recovery mutation, then checked
again during execution. A later edit, missing target, wrong root, link, duplicate
target, or snapshot checksum mismatch blocks automatic recovery. Updated files
recover their exact prior bytes and ordinary permission bits. Created files are
removed only when their current hashes match the applied output.

A failed/cancelled apply attempts rollback only for files still owned by that
apply and still matching its written output. Snapshots remain available if a
partial write or interruption makes safe automatic rollback impossible. Prepared
sessions interrupted after all writes can be recovered when every target matches
the planned after-hash. Partially completed recovery or mismatched files require
manual reconciliation from the protected snapshots; there is no force-overwrite
option. Recovery is not a filesystem-wide atomic transaction or protection
against a malicious concurrent editor.

## Private action history

Default storage is `~/.local/state/devops-agent`, outside application repositories
and build contexts. `DEVOPS_AGENT_STATE_DIR` can select another outside directory.
Storage must be owned by the current user with mode 0700; records are mode 0600.
A symlink storage directory is rejected. Records use temporary files, fsync and
atomic rename. Locks and journal IDs do not depend on repository-supplied names.

Each mutation records its action, authorization, project identity, requested
commands and final result. File applies also record checksums and pre-edit
snapshots before writing. These snapshots preserve original bytes for recovery
and **can contain secrets**; they are private recovery data, never diagnostic
output. `history` exposes only action/approval/status summaries. Keep storage
private and do not publish journal files as reports. No automatic retention or
purging policy is implemented.

Missing/unwritable/unsafe journal storage blocks execution before mutation. A
final journal failure after execution reports failure while preserving the known
environment/cleanup state. An interrupted session may remain `started` or
`prepared`; that is not evidence that the action succeeded or never ran.

## Redaction and untrusted data

CLI reports, verbose output, diagnostics, diagnostic context and journal events
are sanitized. Redaction covers values from local dotenv files, sensitive process
environment names, resolved Compose service environment, sensitive build args,
common password/token/API-key/authorization assignments, URL credentials and PEM
private keys. ANSI escape sequences and control characters are removed. Matching
known values also masks percent-encoded forms. Diagnosis matching uses sanitized
input and fixed actions, never log-provided instructions.

Redaction is conservative, not proof that arbitrary output contains no secrets.
Unknown unlabeled values, custom encodings and secrets outside inspected sources
may evade it; short/common values can over-redact. Protected recovery snapshots
are deliberately not redacted because that would corrupt recovery. Raw internal
proposal/config objects are for execution and must not be forwarded as model
context. Future model integration must use the sanitized reporting interfaces.

## Verification

The offline suite tests recovery, stale edits, Git protection, private storage,
permission restoration, authorization, symlinks/hardlinks, concurrent agent locks,
cancellation, audit failures, secret disclosure in reports/journals, and Docker
scope boundaries. Test journals use temporary storage rather than user history.
The real-Docker retry passed with the step-7 implementation: owned endpoint
readiness, same-origin redirects, healthchecks, port-conflict isolation with the
original owner still healthy, deliberate process exit, authentication rejection,
and scoped cleanup. Evidence is saved in ignored `work/step7-docker.json`.
This uses a cached Node image without building Next.js; additional isolation
refusals and recovery/redaction cases remain covered by the offline suite.


A separate real Next.js acceptance run also passed using generated files without
port overrides: proposal/apply, image build with npm ci, development startup,
owned endpoint at loopback port 3000, HTTP 200 with the fixture page marker, and
verified container/image cleanup. The fixture pins Next.js 16.3.4 and React 19.2.8.
Evidence is in ignored `work/step7-nextjs.json`; the runner is
`tests/docker_nextjs_acceptance.py`. This closes the minimal development build
and startup gap, not production build or arbitrary-repository acceptance.
