"""Reviewable development setup proposals for the supported Next.js workflow."""

import difflib
import hashlib
import json
import os
from pathlib import Path

from agent.detector import detect_stack
from agent.scanner import scan_repo
from agent.understanding import read_text
from agent.safety import Journal, authorize, check_target, project_lock
import shlex

DOCKERFILE = '''# Local development only; not a production deployment image.
FROM node:22
WORKDIR /app
ENV NODE_ENV=development
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci --include=dev --no-audit --no-fund
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]
'''

# Appended last so earlier negations cannot re-include environment files.
IGNORE_RULES = '''# DevOps Agent: local development build exclusions
.git
.devops-agent
node_modules
.next
.venv
__pycache__
.env
.env.*
**/.env
**/.env.*
*.pem
*.key
npm-debug.log*
'''
ENV_FILES = (".env", ".env.development", ".env.local", ".env.development.local")


def digest(content):
    return hashlib.sha256(content).hexdigest()


def development_compose(mounts, host_port=3000):
    compose = ('# Local development only.\nservices:\n  app:\n    build: .\n'
               f'    ports:\n      - "127.0.0.1:{host_port}:3000"\n')
    if mounts:
        compose += "    volumes:\n"
        for filename in mounts:
            compose += (f"      - type: bind\n        source: ./{filename}\n"
                        f"        target: /app/{filename}\n        read_only: true\n"
                        "        bind:\n          create_host_path: false\n")
    return compose


def propose_docker_files(path):
    """Read current evidence and return a proposal without writing any files."""
    root = Path(path).resolve()
    info = scan_repo(str(root))
    analysis = detect_stack(info)
    project = analysis["project"]
    proposal = {
        "schema_version": 1, "path": str(root), "purpose": "local development",
        "status": "blocked", "blockers": list(project["blockers"]),
        "changes": [], "preserved": [], "notes": [], "run_command": None,
    }
    if project["eligibility"] != "eligible":
        return proposal
    if project["setup"] == "existing":
        proposal.update(status="unchanged", preserved=info["dockerfiles"] + info["compose_files"],
                        notes=["Existing setup is preserved. Configuration and runtime compatibility remain unverified."])
        return proposal

    if (root / ".npmrc").exists():
        proposal["blockers"].append({"code": "npm_configuration", "message": "Custom .npmrc configuration needs review before generating an npm ci image.", "next_action": "Resolve custom registry/install requirements; .npmrc will not be copied automatically."})
        return proposal
    mounts = []
    for filename in ENV_FILES:
        if (root / filename).exists():
            # Inspection verifies readability and containment. Never embed values.
            read_text(root, filename)
            mounts.append(filename)
    compose = development_compose(mounts)
    expected = {
        "Dockerfile": (DOCKERFILE, "Use Node 22, install the reviewed npm lockfile with npm ci, and run the declared dev script."),
        "docker-compose.yml": (compose, "Expose the single app on loopback port 3000; mount existing development dotenv files read-only for Next.js to load." if mounts else "Expose the single app on loopback port 3000. No environment file is required."),
    }
    ignore = root / ".dockerignore"
    before_ignore = read_text(root, ".dockerignore") if ignore.exists() else ""
    ignore_content = before_ignore
    if not before_ignore.endswith(IGNORE_RULES):
        ignore_content = before_ignore + ("\n" if before_ignore and not before_ignore.endswith("\n") else "") + IGNORE_RULES
    expected[".dockerignore"] = (ignore_content, "Keep host dependencies and dotenv files out of the image; preserve existing rules and append exclusions last.")

    for filename, (content, reason) in expected.items():
        target = root / filename
        if target.is_symlink() or (target.exists() and not target.is_file()):
            proposal["blockers"].append({"code": "unsafe_target", "message": f"{filename} is a link or non-file.", "next_action": "Resolve the target before proposing changes."})
            return proposal
        before = read_text(root, filename) if target.exists() else None
        if before == content:
            proposal["preserved"].append(filename)
            continue
        proposal["changes"].append({
            "path": filename, "operation": "create" if before is None else "update",
            "before_sha256": None if before is None else digest(before.encode()),
            "content": content, "reason": reason,
            "diff": "".join(difflib.unified_diff((before or "").splitlines(True), content.splitlines(True),
                                               fromfile="/dev/null" if before is None else "a/" + filename,
                                               tofile="b/" + filename)),
        })
    proposal.update(status="ready", run_command="docker compose -f docker-compose.yml up --build",
                    notes=["This creates development configuration only; application readiness has not been verified.",
                           "Environment values are never included in this proposal or baked into the image."])
    inputs = ("package.json", "package-lock.json", ".nvmrc", ".node-version",
              "next.config.js", "next.config.mjs", "next.config.ts", ".env.example", *ENV_FILES)
    combined = hashlib.sha256()
    for filename in inputs:
        file = root / filename
        combined.update(filename.encode())
        combined.update(b"present" if file.exists() else b"absent")
        if file.exists():
            combined.update(read_text(root, filename).encode())
    proposal["inputs_sha256"] = combined.hexdigest()
    # Fingerprint the complete proposal, including its destination. Recompute at apply time.
    proposal["id"] = digest(json.dumps(proposal, sort_keys=True).encode())
    return proposal


def _apply_docker_proposal(proposal):
    """Apply precisely the reviewed proposal, refusing stale inputs and targets."""
    if proposal.get("status") != "ready":
        raise ValueError("Only a ready proposal can be applied.")
    current = propose_docker_files(proposal["path"])
    if current != proposal:
        raise ValueError("Repository or proposal changed. Review a fresh proposal before applying.")
    root = Path(proposal["path"])
    written = []
    try:
        for change in proposal["changes"]:
            target = check_target(root, change["path"])
            previous = target.read_bytes() if change["operation"] == "update" else None
            if target.is_symlink() or (previous is not None and digest(previous) != change["before_sha256"]):
                raise ValueError("A target changed during apply. Review a fresh proposal.")
            if previous is None:
                with target.open("x", encoding="utf-8") as stream:
                    # Track before writing, including partial write failures.
                    written.append((target, previous, target.stat().st_ino))
                    stream.write(change["content"])
            else:
                # Do not follow symlinks introduced after inspection.
                fd = os.open(target, os.O_WRONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    if digest(target.read_bytes()) != change["before_sha256"]:
                        raise ValueError("A target changed during apply.")
                    written.append((target, previous, os.fstat(stream.fileno()).st_ino))
                    stream.write(change["content"])
                    stream.truncate()
    except BaseException:
        for target, previous, inode in reversed(written):
            expected = next(c["content"].encode() for c in proposal["changes"] if c["path"] == target.name)
            if not target.is_symlink() and target.exists() and target.stat().st_ino == inode and target.read_bytes() == expected:
                if previous is None:
                    target.unlink()
                else:
                    target.write_bytes(previous)
        raise
    return {"created": [c["path"] for c in proposal["changes"] if c["operation"] == "create"],
            "updated": [c["path"] for c in proposal["changes"] if c["operation"] == "update"],
            "run_command": proposal["run_command"]}


def _journaled_apply(proposal):
    """Explicit API apply authorizes only this proposal; persist recovery first."""
    if proposal.get("status") != "ready" or propose_docker_files(proposal["path"]) != proposal:
        raise ValueError("Repository or proposal changed. Review a fresh proposal before applying.")
    journal = Journal(proposal["path"], "apply", authorize("apply", explicit=True))
    try:
        journal.snapshot(proposal)
        result = _apply_docker_proposal(proposal)
    except BaseException:
        journal.finish("failed", {"error": "Apply failed; rollback attempted. Preserve snapshots for manual recovery if files remain."})
        raise
    try:
        journal.finish("applied", result)
    except (OSError, ValueError):
        raise ValueError(f"Files were applied but final journal recording failed. Inspect recovery session {journal.id}.") from None
    result["session_id"] = journal.id
    result["recovery_command"] = shlex.join(["devops-agent", "recover", proposal["path"], journal.id])
    return result


def apply_docker_proposal(proposal):
    with project_lock(proposal["path"]):
        return _journaled_apply(proposal)
