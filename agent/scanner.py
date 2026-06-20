from pathlib import Path


IMPORTANT_FILES = [
    "package.json",
    "Gemfile",
    "requirements.txt",
    "pyproject.toml",
    "manage.py",
]

CONFIG_FILES = [
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".env.example",
    "config/credentials.yml",
    "config/credentials.yml.enc",
    "config/master.key",
]


def scan_repo(path: str):
    repo_path = Path(path).resolve()

    found_files = []

    for file_name in IMPORTANT_FILES:
        if (repo_path / file_name).exists():
            found_files.append(file_name)

    dockerfiles = []
    compose_files = []
    config_files = []
    workflow_files = []

    workflows_dir = repo_path / ".github" / "workflows"

    if workflows_dir.exists():
        workflow_files.extend(
            [f.name for f in workflows_dir.glob("*.yml")]
        )
        workflow_files.extend(
            [f.name for f in workflows_dir.glob("*.yaml")]
        )

    for file in repo_path.iterdir():
        if not file.is_file():
            continue

        filename = file.name.lower()

        if "dockerfile" in filename:
            dockerfiles.append(file.name)

        if (
            "compose" in filename
            or file.name in ["local.yml", "local_mac.yml"]
        ):
            compose_files.append(file.name)

    for config_file in CONFIG_FILES:
        if (repo_path / config_file).exists():
            config_files.append(config_file)

    return {
        "path": str(repo_path),
        "found_files": found_files,
        "dockerfiles": dockerfiles,
        "compose_files": compose_files,
        "config_files": config_files,
        "workflow_files": workflow_files,
    }