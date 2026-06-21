from pathlib import Path


def has_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def detect_python(repo_path, files, detected, services, runtime, startup_commands):
    if "pyproject.toml" in files:
        detected.append("Python app")
        runtime.append("Python runtime")

    if "requirements.txt" in files:
        detected.append("Python dependencies file")
        runtime.append("Python runtime")

        requirements_path = repo_path / "requirements.txt"

        if requirements_path.exists():
            text = requirements_path.read_text(errors="ignore").lower()

            if has_any(text, ["psycopg", "postgres"]):
                services.append("PostgreSQL")

            if has_any(text, ["pymongo", "motor"]):
                services.append("MongoDB")

            if has_any(text, ["mysqlclient", "pymysql"]):
                services.append("MySQL/MariaDB")

            if "sqlite" in text:
                services.append("SQLite")

            if "redis" in text:
                services.append("Redis")

            if "firebase-admin" in text:
                services.append("Firebase Firestore")

            if "boto3" in text:
                services.append("AWS Services")

            if "django-storages" in text:
                services.append("AWS S3")

            if has_any(text, ["celery", "rq"]):
                services.append("Background jobs")

            if has_any(text, ["django-allauth", "authlib"]):
                services.append("Authentication")

            if "pillow" in text:
                services.append("Image processing")

            if has_any(text, ["reportlab", "weasyprint"]):
                services.append("PDF generation")

            if "fastapi" in text:
                detected.append("FastAPI app")
                startup_commands.append("uvicorn main:app --reload")

            if "flask" in text:
                detected.append("Flask app")
                startup_commands.append("flask run")

            if "django" in text:
                detected.append("Django app")
                startup_commands.append("python manage.py runserver")

    if "manage.py" in files and "Django app" not in detected:
        detected.append("Django app")
        runtime.append("Python runtime")
        startup_commands.append("python manage.py runserver")


def detect_node(repo_path, files, detected, services, runtime, startup_commands):
    if "package.json" not in files:
        return

    detected.append("Node.js app")
    runtime.append("Node.js runtime")

    package_json_path = repo_path / "package.json"

    if not package_json_path.exists():
        return

    text = package_json_path.read_text(errors="ignore").lower()

    if '"next"' in text:
        detected.append("Next.js app")

    if "vue" in text:
        detected.append("Vue app")

    if "supabase" in text:
        services.append("Supabase/PostgreSQL")

    if has_any(text, ["mongoose", "mongodb"]):
        services.append("MongoDB")

    if '"pg"' in text:
        services.append("PostgreSQL")

    if "mysql2" in text:
        services.append("MySQL/MariaDB")

    if "sqlite" in text:
        services.append("SQLite")

    if has_any(text, ["redis", "ioredis"]):
        services.append("Redis")

    if has_any(text, ["firebase", "firestore"]):
        services.append("Firebase Firestore")

    if has_any(text, ["aws-sdk", "@aws-sdk/client-s3"]):
        services.append("AWS Services")

    if has_any(text, ["@aws-sdk/client-s3", "multer-s3"]):
        services.append("AWS S3")

    if has_any(text, ["bull", "bullmq"]):
        services.append("Background jobs")

    if has_any(text, ["passport", "next-auth"]):
        services.append("Authentication")

    if "multer" in text:
        services.append("File uploads")

    if has_any(text, ["pdfkit", "jspdf", "pdf-parse"]):
        services.append("PDF processing")

    if '"dev"' in text:
        startup_commands.append("npm run dev")
    elif '"start"' in text:
        startup_commands.append("npm start")


def detect_ruby(repo_path, files, detected, services, runtime, startup_commands):
    if "Gemfile" not in files:
        return

    detected.append("Ruby app")
    runtime.append("Ruby runtime")

    gemfile_path = repo_path / "Gemfile"

    if not gemfile_path.exists():
        return

    text = gemfile_path.read_text(errors="ignore").lower()

    if "rails" in text:
        detected.append("Rails app")
        runtime.append("Rails runtime")

    if has_any(text, ['gem "pg"', "gem 'pg'"]):
        services.append("PostgreSQL")

    if has_any(text, ['gem "mysql2"', "gem 'mysql2'"]):
        services.append("MySQL/MariaDB")

    if "sqlite3" in text:
        services.append("SQLite")

    if "redis" in text:
        services.append("Redis")

    if "sidekiq" in text:
        services.append("Sidekiq")

    if has_any(text, ["aws-sdk-s3", "carrierwave-aws"]):
        services.append("AWS S3")

    if "aws-sdk-rails" in text:
        services.append("AWS Services")

    if "omniauth-cas" in text:
        services.append("CAS authentication")

    if "carrierwave" in text:
        services.append("File uploads")

    if has_any(text, ["wicked_pdf", "wkhtmltopdf"]):
        services.append("PDF generation")

    startup_commands.append("rails server")


def detect_runtime_from_infra(repo_info, runtime, startup_commands):
    if repo_info["compose_files"] or repo_info["dockerfiles"]:
        runtime.append("Docker-based development")

    compose_files = repo_info["compose_files"]

    if "docker-compose.yml" in compose_files:
        startup_commands.insert(0, "docker compose up")

    for compose_file in compose_files:
        if compose_file != "docker-compose.yml":
            startup_commands.append(f"docker compose -f {compose_file} up")


def detect_missing_and_recommendations(repo_info, missing, recommendations):
    is_component = repo_info.get("is_component", False)

    if is_component:
        if not repo_info["config_files"]:
            recommendations.append(
                "Component appears to be managed by root-level Docker/config."
            )
        return
    
    if not repo_info["dockerfiles"]:
        missing.append("Dockerfile")
        recommendations.append(
            "Add a Dockerfile so the app can run consistently in containers."
        )

    if not repo_info["compose_files"]:
        missing.append("docker-compose.yml")
        recommendations.append("Add Docker Compose for local multi-service setup.")

    uses_rails_credentials = (
        "config/credentials.yml.enc" in repo_info["config_files"]
        or "config/credentials.yml" in repo_info["config_files"]
    )

    if not repo_info["config_files"]:
        missing.append("Environment configuration")
        recommendations.append(
            "Add a .env, .env.example, or framework-specific credentials file."
        )
    elif ".env.example" not in repo_info["config_files"] and not uses_rails_credentials:
        recommendations.append(
            "Add a .env.example file to document required environment variables."
        )

    if not repo_info["workflow_files"]:
        missing.append("GitHub Actions workflow")
        recommendations.append("Add CI so tests/builds run automatically on push.")


def apply_component_summary(repo_info, detected, services, runtime):
    components = repo_info.get("components", [])

    if not components:
        return

    detected.append("Full-stack / multi-component app")

    for component in components:
        component_analysis = detect_stack(component)
        role = component.get("role", "component")

        for item in component_analysis["detected"]:
            if item == "Unknown stack":
                continue

            if role == "frontend":
                detected.append(f"{item} frontend")
            elif role == "backend":
                detected.append(f"{item} backend")
            else:
                detected.append(f"{item} component")

        for service in component_analysis["services"]:
            services.append(service)

        for item in component_analysis["runtime"]:
            runtime.append(item)


def detect_stack(repo_info):
    repo_path = Path(repo_info["path"])
    files = set(repo_info["found_files"])

    detected = []
    services = []
    runtime = []
    startup_commands = []
    missing = []
    recommendations = []

    detect_python(repo_path, files, detected, services, runtime, startup_commands)
    detect_node(repo_path, files, detected, services, runtime, startup_commands)
    detect_ruby(repo_path, files, detected, services, runtime, startup_commands)
    detect_runtime_from_infra(repo_info, runtime, startup_commands)
    apply_component_summary(repo_info, detected, services, runtime)
    detect_missing_and_recommendations(repo_info, missing, recommendations)

    if not detected:
        detected.append("Unknown stack")

    return {
        "detected": sorted(set(detected)),
        "services": sorted(set(services)),
        "runtime": sorted(set(runtime)),
        "startup_commands": list(dict.fromkeys(startup_commands)),
        "missing": missing,
        "recommendations": recommendations,
    }