from pathlib import Path


IMPORTANT_FILES = [
    "package.json",
    "Gemfile",
    "requirements.txt",
    "pyproject.toml",
    "manage.py",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".env",
    ".env.example",
]


def scan_repo(path: str):
    repo_path = Path(path).resolve()

    found_files = []

    for file_name in IMPORTANT_FILES:
        if (repo_path / file_name).exists():
            found_files.append(file_name)

    return {
        "path": str(repo_path),
        "found_files": found_files,
    }