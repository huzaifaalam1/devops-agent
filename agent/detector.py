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

        gemfile_path = repo_path / "Gemfile"

        if gemfile_path.exists():
            gemfile_text = gemfile_path.read_text(errors="ignore").lower()

            if "rails" in gemfile_text:
                detected.append("Rails app")

    if "manage.py" in files:
        detected.append("Django app")

    if not repo_info["dockerfiles"]:
        missing.append("Dockerfile")
        recommendations.append(
            "Add a Dockerfile so the app can run consistently in containers."
        )

    if not repo_info["compose_files"]:
        missing.append("docker-compose.yml")
        recommendations.append(
            "Add Docker Compose for local multi-service setup."
        )

    uses_rails_credentials = (
        "config/credentials.yml.enc" in repo_info["config_files"]
        or "config/credentials.yml" in repo_info["config_files"]
    )

    if not repo_info["config_files"]:
        missing.append("Environment configuration")
        recommendations.append(
            "Add a .env, .env.example, or framework-specific credentials file."
        )
    elif (
        ".env.example" not in repo_info["config_files"]
        and not uses_rails_credentials
    ):
        recommendations.append(
            "Add a .env.example file to document required environment variables."
        )

    if not repo_info["workflow_files"]:
        missing.append("GitHub Actions workflow")
        recommendations.append(
            "Add CI so tests/builds run automatically on push."
        )

    if not detected:
        detected.append("Unknown stack")

    return {
        "detected": detected,
        "missing": missing,
        "recommendations": recommendations,
    }