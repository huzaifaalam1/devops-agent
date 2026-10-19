# Existing local stacks and initialization

The existing Compose file is the runtime contract. Framework detection determines
what the agent can **generate**, not whether an already-configured repository can
run. A single app container can start several processes, including Django and Vue.

For media-facility the reference is `docker-compose.local.yml`, its selected
`LocalDockerfile`, and `entrypoint.sh`. `BaseDockerfile` describes a prerequisite
image; the agent does not silently rebuild or overwrite that shared image tag.
Missing base images therefore remain actionable build failures.

## Reusable startup pattern

Use this sequence for mixed-language and single-language repositories:

1. Compose declares dependencies and waits for their health checks.
2. The selected Dockerfile installs the declared runtimes/dependencies and copies
   the application plus its startup script.
3. The startup script performs **declared** initialization: migrations, dependency
   preparation and optional seed/user creation. The review discloses these effects.
4. The script starts the app processes. Each published application endpoint must
   pass readiness; one working frontend cannot hide an unavailable backend.
5. Retained environments have exact container ownership for status and stop.

This is a lifecycle pattern, not permission to invent migration commands or copy
media-facility's passwords, image tags, framework versions or directory names.
Use repository evidence for those values. New mixed-stack file generation is not
implemented by this change; existing configurations use the shared execution path.

## Reviewed isolation

`validate_runtime` accepts `existing_setup=true`, an explicit `compose_file`, and
`isolated_stack=true`. The review shows the selected configuration, Dockerfiles,
root startup scripts, database-init evidence and host UID/GID defaults. It grants
execution of the existing startup including migrations/seeding against **new,
empty, project-scoped volumes**, not adoption of the user's current database.

Repository bind mounts are replaced with bounded copies in private agent storage.
Installed dependency/build/cache directories are omitted. Original source paths
are not mounted writable. External mounts, symlinks, explicitly shared resources,
privileged services and unsafe build options remain refused. Loopback ports are
preserved; occupied ports are reported rather than reassigned. A successful kept
run retains the copies/volumes; stop preserves them. Non-retained successful runs
remove the test copies after cleanup. If cleanup fails, copies are retained for
inspection. Future cleanup of stopped environments is not implemented here.

`LOCAL_UID` and `LOCAL_GID` default to the host IDs when absent; existing environment
values win. Missing additional variables still fail through Compose/build checks.

Every published TCP endpoint currently receives an HTTP check. The selected
`container_port` uses the reviewed `health_path`; other endpoints use `/`. Stacks
that publish non-HTTP database ports or need multiple distinct health paths require
additional readiness support. HTTP readiness is not complete business/API testing.
The media-facility pilot also checks Django's migration state separately.

## Verification

See retained sanitized reports in `evidence/`. The pilot copies tracked working
files from media-facility, builds using its existing setup, checks both endpoints
in the same container, checks migration state, exercises reviewed stop, removes
only pilot resources, and verifies the source hashes and unrelated containers.
The live variant uses the actual configured model and trusted harness approvals.

## Reproduce through chat

From the media-facility root, start a **new** chat so it loads the updated tools:

```sh
devops-agent chat .
```

Ask: `Can you run this repo locally and leave it running?`
Approve provider use, then review the isolated-stack startup. This launches a new
local test database and copies of the source; it does not reopen the existing
application database or provide live reload from edits to the original source.

Readiness suggestions are derived from the declared Django admin URL and the
startup script's explicit `runserver` port, where both are unambiguous. They are
reviewed probe candidates and must still pass real HTTP checks.

Early failures are retained rather than counted as passes: a test harness used a
noncanonical macOS temporary path; another expected full container state in a
compact chat summary; the live planner initially selected `/` for Django and got
404. The route/port suggestion fixes that last product issue. A temporary import
error and a fake-secret test collision were also corrected before final checks.

Final result: **359 offline tests passed**. The final live-model pilot passed both
HTTP checks in the same app container, migration-state verification, source
preservation, reviewed stop and cleanup. Unrelated running containers were
preserved. This verifies the tested local startup, not all business/API flows.
