from pathlib import Path


def detect_stack(repo_info):
    repo_path = Path(repo_info["path"])
    files = set(repo_info["found_files"])

    detected = []
    missing = []
    recommendations = []

    if "pyproject.toml" in files:
        detected.append("Python app")

    if "requirements.txt" in files:
        detected.append("Python dependencies file")

    if "package.json" in files:
        detected.append("Node.js app")

    if "Gemfile" in files:
        detected.append("Ruby app")

    if "manage.py" in files:
        detected.append("Django app")

    if "Dockerfile" not in files:
        missing.append("Dockerfile")
        recommendations.append("Add a Dockerfile so the app can run consistently in containers.")

    if "docker-compose.yml" not in files and "docker-compose.yaml" not in files:
        missing.append("docker-compose.yml")
        recommendations.append("Add Docker Compose for local multi-service setup.")

    if ".env.example" not in files:
        missing.append(".env.example")
        recommendations.append("Add an environment variable template for local setup.")

    github_actions_path = repo_path / ".github" / "workflows"

    if not github_actions_path.exists():
        missing.append("GitHub Actions workflow")
        recommendations.append("Add CI so tests/builds run automatically on push.")

    if not detected:
        detected.append("Unknown stack")

    return {
        "detected": detected,
        "missing": missing,
        "recommendations": recommendations,
    }