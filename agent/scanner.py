import os
import re
from pathlib import Path


IMPORTANT_FILES = [
    "package.json",
    "Gemfile",
    "requirements.txt",
    "pyproject.toml",
    "manage.py",
    "go.mod",
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
    "work",
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
        if (repo_path / file_name).is_file():
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

        if re.fullmatch(r"dockerfile(?:[._-].+)?", filename) and file.suffix.lower() not in {".md", ".txt", ".bak", ".backup", ".old"}:
            dockerfiles.append(file.name)

        if re.fullmatch(r"(?:docker-compose|compose)(?:[._-][^.]+)?\.ya?ml", filename) or re.fullmatch(r"local(?:_(?:mac|linux))?\.ya?ml", filename):
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
        "dockerfiles": sorted(dockerfiles),
        "compose_files": sorted(compose_files),
        "config_files": config_files,
        "workflow_files": workflow_files,
    }


def find_components(root_path: Path, max_depth: int = 2):
    components = []

    def fail_scan(error):
        raise error

    for parent, directories, _ in os.walk(root_path, followlinks=False, onerror=fail_scan):
        depth = len(Path(parent).relative_to(root_path).parts)
        directories[:] = sorted(
            name for name in directories
            if not name.startswith(".") and name not in IGNORED_DIRS
            and not (Path(parent) / name).is_symlink()
        ) if depth < max_depth else []
        if depth == 0:
            continue
        child_info = scan_single_repo(Path(parent))
        if child_info["found_files"]:
            child_info["is_component"] = True
            components.append(child_info)

    return components


def scan_repo(path: str, max_depth: int = 2):
    root_path = Path(path).resolve()
    if not root_path.is_dir():
        raise ValueError("Select an existing application directory.")
    root_info = scan_single_repo(root_path)

    root_info["components"] = find_components(root_path, max_depth)

    return root_info
