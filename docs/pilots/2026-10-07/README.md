# Pilot follow-up: unsupported guidance and explicit Compose selection

October 7, 2026. Uncommitted candidate based on `4b56b8e`; tested source hashes
are in `verification.json`. All 189 offline tests pass, including six new pilot
regression tests. The previous four-repository screening is retained unchanged.

## Verified changes

- Django root/backend and Vue frontend analysis no longer recommends npm lockfiles,
  Node 22 or Next.js startup changes. Framework detection and component candidates
  remain available; automated execution stays blocked.
- `validate --compose-file FILE` selects a discovered root Compose file. The
  database pilot without an explicit selection now returns a selection error;
  selecting `docker-compose.dev.yml` passes the real Docker configuration check.
- Explicit selection removes variant ambiguity for validation. Runtime requests
  still stop at other eligibility blockers: the Docker sample retains package
  manager/runtime blockers; the database sample retains environment, dependency
  and runtime blockers. Those refusals are expected, not startup successes.
- Tests cover default single-file selection, no Docker call on ambiguity or
  invalid paths, selected-file dispatch, and preservation of other eligibility
  blockers. Resource isolation in the validator is unchanged.

## Remaining limits

Only a single standalone root Compose file can be selected; Compose override
merging is not implemented. Generation still preserves existing variants and
will not apply a new template over them. Unused Dockerfile runtime declarations
are still checked conservatively. Existing-setup runtime eligibility, precise
redaction and Compose/environment reconciliation remain separate follow-ups.
No applications started, repair was not exercised, and no API calls were made.
This is not completion of the runtime pilot. Changes remain uncommitted.

## Direct original-checkout verification

Reran 24 real CLI invocations on the four original Desktop/repos checkouts,
not mocks or copied fixtures. `direct-checkouts.json` records exact commands,
exit codes, timings, source hashes and upstream revisions. Both Next.js Compose
examples passed explicitly selected Docker configuration checks. The database
example without selection correctly refused ambiguity. Django/Vue component
analysis retained only the unsupported-framework blocker, with no Next.js repair
instructions. All runtime requests still stopped at selection or eligibility;
no application was built or started. Django Compose also still lacks its `.env`.
Byte-level file snapshots and Git status confirm all four original checkouts are
unchanged. Container inventory is unchanged. These checks confirm the two fixes
on external repos, but do not establish end-to-end application startup.
