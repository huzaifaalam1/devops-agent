# Actionable troubleshooting — step 6

A failed `validate` now includes a deterministic diagnosis with observed symptoms,
source-linked evidence excerpts, a likely cause, confidence, uncertainty, a
recommended action, expected impact, and a resolution check. Advice is never
executed automatically. A diagnosis does not change validation success or exit codes.

```sh
devops-agent validate /path/to/app --run
devops-agent validate /path/to/app --run --verbose
devops-agent validate /path/to/app --run --json
```

The default output shows the diagnosis and next steps. `--verbose` adds captured
command output and service logs, including cleanup failures. `--json` returns the
structured report, including diagnosis and captured details; when both flags are
present, output remains JSON. These are the existing bounded captures, not an
unlimited live log stream. Logs and evidence may contain secrets: comprehensive
redaction remains step 7 work. Review reports before sharing them.

## Initial failure catalog

| Failure | Evidence | Action and resolution check |
| --- | --- | --- |
| Occupied host port | Binding/preflight error | Identify the owner and change this project's published port; rerun and verify the new endpoint. Never automatically stop the owner. |
| Missing configuration | Explicit missing-variable message or analysis blocker | Supply real required values through the expected config; clear analysis blockers and verify runtime readiness. |
| Unavailable dependency | Connection-refused or hostname-resolution message | Identify the destination, inspect its service health/address, retry the failing operation, and revalidate. |
| Dependency installation | Recognized package-resolution, lockfile, integrity, compatibility, or registry status error in build output | Correct the specific lockfile/registry/runtime issue; require a successful build before separately checking runtime. A generic npm script failure is insufficient. |
| Docker unavailable | Missing executable, daemon connection, or socket permission error | Check Docker client/server and context; restore local access, then retry. |
| Docker storage | Disk-full or I/O error | Inspect host/Docker storage and restore health without blanket pruning; retry the failed stage. |
| HTTP authentication | Observed 401/403 | Select an existing unauthenticated readiness route; verify final 2xx without disabling app authentication. |
| Cleanup failure | Structured cleanup failure | Inspect resources under the reported run label, recover Docker access, and verify scoped cleanup. |
| Ruby gems (legacy recognition) | Bundler missing-gem message | Check lockfile and installed bundle in the project's own workflow; this does not expand supported runtime scope. |
| Unknown | Unrecognized or insufficient evidence | Inspect captured stage/output and reproduce the earliest failure before proposing an edit. |

Confidence describes recognition of a failure category, not proof of its root
cause. Connection and installation diagnoses retain multiple possible causes.
The report presents one supported diagnosis; multiple failures may coexist.
Cleanup failure takes precedence over earlier errors. Successful command warnings
are excluded from matching. Log text is data and is never copied into executable
repair instructions. Evidence is bounded to three excerpts of 500 characters.

Missing configuration can be diagnosed at the eligibility gate without starting
Docker. Other eligibility blockers remain visible with their existing next actions.
Unknown failures remain explicit and carry manual investigation and verification
instructions rather than claiming a fix or inventing evidence.

## Verification

`tests/test_diagnostics.py` covers the catalog, exact evidence provenance,
uncertainty, stale successful-command output, unknowns, cleanup precedence,
HTTP authentication, large untrusted log text, CLI summary/details/JSON modes,
and missing-variable preflight without Docker. The complete offline suite has
96 passing checks. No new Docker build is needed for this advice-only change;
step 5's real runtime evidence remains separate. Historical baseline files are
unchanged.
