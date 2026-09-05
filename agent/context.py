import subprocess
from pathlib import Path


MAX_LOG_LINES = 150


def run_context_command(
    command: list[str],
    repo_path: Path,
    timeout: int = 15,
) -> dict:
    try:
        result = subprocess.run(
            command,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        return {
            "command": " ".join(command),
            "success": False,
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds: {error}",
            "returncode": None,
        }
    except OSError as error:
        return {
            "command": " ".join(command),
            "success": False,
            "stdout": "",
            "stderr": str(error),
            "returncode": None,
        }

    return {
        "command": " ".join(command),
        "success": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }


def collect_git_context(repo_path: Path) -> dict:
    git_check = run_context_command(
        ["git", "rev-parse", "--is-inside-work-tree"],
        repo_path,
    )

    if (
        not git_check["success"]
        or git_check["stdout"].strip().lower() != "true"
    ):
        return {
            "is_git_repo": False,
            "branch": None,
            "dirty": False,
            "tracked_changes": False,
            "untracked_changes": False,
            "changed_files": [],
            "untracked_files": [],
        }

    branch_result = run_context_command(
        ["git", "branch", "--show-current"],
        repo_path,
    )

    status_result = run_context_command(
        ["git", "status", "--porcelain"],
        repo_path,
    )

    branch = None

    if branch_result["success"]:
        branch = branch_result["stdout"].strip() or None

    changed_files = []
    untracked_files = []

    if status_result["success"]:
        for line in status_result["stdout"].splitlines():
            if len(line) < 4:
                continue

            status = line[:2]
            file_path = line[3:].strip()

            if status == "??":
                untracked_files.append(file_path)
            else:
                changed_files.append(file_path)

    tracked_changes = bool(changed_files)
    untracked_changes = bool(untracked_files)

    return {
        "is_git_repo": True,
        "branch": branch,
        "dirty": tracked_changes or untracked_changes,
        "tracked_changes": tracked_changes,
        "untracked_changes": untracked_changes,
        "changed_files": changed_files,
        "untracked_files": untracked_files,
    }


def collect_file_context(repo_path: Path) -> dict:
    artifact_groups = {
        "ruby": [
            "Gemfile",
            "Gemfile.lock",
        ],
        "python": [
            "requirements.txt",
            "pyproject.toml",
            "poetry.lock",
            "Pipfile",
        ],
        "node": [
            "package.json",
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
        ],
        "environment": [
            ".env",
            ".env.example",
            ".env.local",
            ".env.development",
            ".env.production",
        ],
        "database": [
            "db/schema.rb",
            "db/structure.sql",
            "prisma/schema.prisma",
        ],
    }

    discovered = {}

    for category, filenames in artifact_groups.items():
        discovered[category] = [
            filename
            for filename in filenames
            if (repo_path / filename).exists()
        ]

    return discovered


def trim_logs(
    logs: str,
    max_lines: int = MAX_LOG_LINES,
) -> str:
    if not logs:
        return ""

    lines = logs.splitlines()

    if len(lines) <= max_lines:
        return logs

    return "\n".join(lines[-max_lines:])


def collect_validation_context(
    validation_result: dict | None,
) -> dict:
    if validation_result is None:
        return {}

    application_check = validation_result.get("application_check")

    return {
        "success": validation_result.get("success"),
        "phase": validation_result.get("phase"),
        "expected_services": validation_result.get(
            "expected_services",
            [],
        ),
        "running_services": validation_result.get(
            "running_services",
            [],
        ),
        "stopped_services": validation_result.get(
            "stopped_services",
            [],
        ),
        "application_check": application_check,
        "logs": trim_logs(
            validation_result.get("logs", "") or ""
        ),
    }


def collect_stack_context(
    analysis: dict | None,
) -> dict:
    if analysis is None:
        return {}

    return {
        "detected": analysis.get("detected", []),
        "services": analysis.get("services", []),
        "runtime": analysis.get("runtime", []),
        "startup_commands": analysis.get(
            "startup_commands",
            [],
        ),
    }


def collect_diagnostic_context(
    path: str,
    analysis: dict | None = None,
    validation_result: dict | None = None,
) -> dict:
    repo_path = Path(path).resolve()

    context = {
        "repository": {
            "path": str(repo_path),
            "name": repo_path.name,
            "exists": repo_path.exists(),
            "is_directory": repo_path.is_dir(),
        },
        "git": {},
        "files": {},
        "stack": {},
        "validation": {},
    }

    if not repo_path.exists() or not repo_path.is_dir():
        return context

    context["git"] = collect_git_context(repo_path)
    context["files"] = collect_file_context(repo_path)
    context["stack"] = collect_stack_context(analysis)
    context["validation"] = collect_validation_context(
        validation_result
    )

    return context