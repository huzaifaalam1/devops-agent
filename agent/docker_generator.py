from pathlib import Path


PYTHON_DOCKERFILE = """FROM python:3.12-slim

WORKDIR /app

COPY . .

RUN pip install -e .

CMD ["devops-agent", "--help"]
"""

DOCKERIGNORE = """.venv
__pycache__
*.pyc
.git
.env
"""


def generate_docker_files(path: str):
    repo_path = Path(path).resolve()

    dockerfile_path = repo_path / "Dockerfile"
    dockerignore_path = repo_path / ".dockerignore"

    created = []

    if not dockerfile_path.exists():
        dockerfile_path.write_text(PYTHON_DOCKERFILE)
        created.append("Dockerfile")

    if not dockerignore_path.exists():
        dockerignore_path.write_text(DOCKERIGNORE)
        created.append(".dockerignore")

    return created