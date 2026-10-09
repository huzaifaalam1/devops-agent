# Structured tool boundary — step 3

`agent.tools.ToolRegistry` is the internal adapter for step 4. It is bound to one
canonical repository directory and exposes JSON-schema-shaped parameter metadata.
The [step-4 loop](agent-loop.md) now connects this boundary to terminal reviews.

| Tool | Effect | Authorization |
| --- | --- | --- |
| runtime_status | Live state of journaled containers | Read-only Docker queries |
| stop_runtime | Stop exact retained container IDs, preserving data | Trusted UI approval of runtime snapshot |
| inspect_repository | Static repository findings | Automatic within selected root |
| read_file | Read supported root configuration text | Automatic within selected root |
| patch_file | Apply one exact text replacement | Trusted UI approval of displayed diff |
| propose_docker | Docker diffs and eligibility | Automatic within selected root |
| apply_docker | Apply a ready exact Docker proposal | Trusted UI approval of review |
| validate_runtime | Compose resolution; optional build/run | Trusted UI approval, even for config-only Docker invocation |

There is no arbitrary shell, path override, credential setter, approval tool,
cloud operation or database migration tool. Repair and retained-log adapters can
be added with explicit schemas and provenance checks when their loop workflows
are implemented; existing CLI repair remains available. No additional model or
orchestration dependency is introduced.

## Review and approval lifecycle

1. The caller validates a tool name and strict parameter object. Unknown fields,
   paths outside root Compose selection, incorrect types (including boolean-as-int),
   invalid readiness paths and out-of-range timeouts/ports are refused.
2. `review(name, params)` prepares a concrete diff for apply, or selected Compose
   and root Dockerfile contents plus parameters/effect for validation. Outputs
   are redacted. Inputs are fingerprinted before and after review preparation.
3. A **trusted UI**, following human authorization, calls `approve(review_id)`.
   This method is not present in the model schema or tool dispatch. Tool output,
   repository text and model JSON cannot issue grants.
4. The executor supplies the grant separately to `execute`; model parameters
   cannot carry approval. The exact action/parameters, repository identity,
   fingerprint and expiry must match. A grant is consumed before execution,
   including a backend failure, so retrying requires a new reviewed authorization.
5. Apply and runtime validation retain existing journals, recovery, eligibility,
   isolation and cleanup checks. Validation now shares one policy function with
   the CLI instead of calling the low-level Docker validator directly.

Reviews expire after ten minutes. Up to 32 reviews and 32 grants can be pending;
a new registry clears them. Grants do not transfer between registries or persist
across restart. Future resume must obtain fresh approval after reconciling state.

Docker fingerprints bind root identity, file paths/content/modes and process
environment. Only `.git` directories are excluded. The bound is 250,000 entries
and 2 GiB, read in chunks. Internal symlinks are recorded and their targets remain
covered by traversal; external, broken or Git-metadata links are refused.
Configuration patches instead fingerprint their selected file and root identity;
installed dependencies do not affect approval of that edit. See the
[configuration editing contract](agent-loop.md#conversational-configuration-editing).
No plaintext secret values are returned from fingerprints.

This is an application authorization boundary, not a Python sandbox: trusted
host code controls the registry and approval callback. Filesystem hashing is not
an atomic snapshot against unrelated concurrent editors. Existing action-time
checks remain necessary; do not advertise protection against arbitrary hostile
host processes. Execution may run repository code once that operation is approved.

## Verification

Tests cover unknown/invalid tools, forged approval fields, stale input/environment,
changed parameters, cross-registry/replayed/expired grants, symlinks, secret
redaction, untrusted output, real temporary-file apply, and preservation of CLI
eligibility/isolation failure behavior. Docker execution in boundary tests is
mocked; this proves dispatch policy, not new runtime/model behavior. Full agent
workflow verification belongs to step 4. Pre-existing tracked bytecode changes
were left untouched.

Checkpoint verification: **218 full-suite tests passed**, including 11 tool
boundary tests. A focused rerun of all 11 boundary tests also passed after adding
malformed tool-name/payload cases. Evidence: ignored
`work/v2-step3/offline.json`. Documentation links and `git diff --check` passed.
No live model calls or real Docker runs were made for this internal boundary change.
