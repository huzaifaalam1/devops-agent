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

IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "tmp",
    "log",
    "vendor",
    "devops_agent.egg-info",
    ".next",
    "dist",
    "build",
    "coverage",
}


def infer_component_role(name: str):
    lower = name.lower()

    if any(word in lower for word in ["frontend", "client", "web", "ui"]):
        return "frontend"

    if any(word in lower for word in ["backend", "server", "api"]):
        return "backend"

    return "component"


def scan_single_repo(path: Path):
    repo_path = path.resolve()

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
        workflow_files.extend([f.name for f in workflows_dir.glob("*.yml")])
        workflow_files.extend([f.name for f in workflows_dir.glob("*.yaml")])

    for file in repo_path.iterdir():
        if not file.is_file():
            continue

        filename = file.name.lower()

        if "dockerfile" in filename:
            dockerfiles.append(file.name)

        if "compose" in filename or file.name in ["local.yml", "local_mac.yml"]:
            compose_files.append(file.name)

    for config_file in CONFIG_FILES:
        if (repo_path / config_file).exists():
            config_files.append(config_file)

    return {
        "path": str(repo_path),
        "name": repo_path.name,
        "role": infer_component_role(repo_path.name),
        "is_component": False,
        "found_files": found_files,
        "dockerfiles": dockerfiles,
        "compose_files": compose_files,
        "config_files": config_files,
        "workflow_files": workflow_files,
    }


def find_components(root_path: Path, max_depth: int = 2):
    components = []

    for child in root_path.rglob("*"):
        if not child.is_dir():
            continue

        relative_parts = child.relative_to(root_path).parts

        if len(relative_parts) > max_depth:
            continue

        if any(part.startswith(".") for part in relative_parts):
            continue

        if any(part in IGNORED_DIRS for part in relative_parts):
            continue

        child_info = scan_single_repo(child)

        if child_info["found_files"]:
            child_info["is_component"] = True
            components.append(child_info)

    return components


def scan_repo(path: str, max_depth: int = 2):
    root_path = Path(path).resolve()
    root_info = scan_single_repo(root_path)

    root_info["components"] = find_components(root_path, max_depth)

    return root_info