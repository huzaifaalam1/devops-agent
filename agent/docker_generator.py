from pathlib import Path


NODE_DOCKERFILE = """FROM node:22

WORKDIR /app

COPY package*.json ./

RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
"""

NEXT_DOCKERFILE = NODE_DOCKERFILE

PYTHON_DOCKERFILE = """FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
"""

RAILS_DOCKERFILE = """FROM ruby:3.2

WORKDIR /app

RUN apt-get update -qq && apt-get install -y build-essential nodejs default-mysql-client postgresql-client

COPY Gemfile Gemfile.lock ./

RUN bundle install

COPY . .

EXPOSE 3000

CMD ["rails", "server", "-b", "0.0.0.0"]
"""

DOCKERIGNORE = """.git
.env
.env.local
.env.development
.env.production

node_modules
.next
dist
build
coverage

__pycache__
*.pyc
.venv
venv

tmp
log

vendor/bundle
*.egg-info
"""


def choose_dockerfile(analysis: dict):
    detected = analysis["detected"]

    if "Next.js app" in detected:
        return NEXT_DOCKERFILE

    if "Node.js app" in detected:
        return NODE_DOCKERFILE

    if "Rails app" in detected or "Ruby app" in detected:
        return RAILS_DOCKERFILE

    if "Django app" in detected or "Python app" in detected:
        return PYTHON_DOCKERFILE

    return None


def get_app_port(analysis: dict):
    detected = analysis["detected"]

    if "Django app" in detected or "Python app" in detected:
        return "8000"

    return "3000"


def generate_compose(analysis: dict):
    services = analysis["services"]
    app_port = get_app_port(analysis)

    compose = f"""services:
  app:
    build: .
    ports:
      - "{app_port}:{app_port}"
    env_file:
      - .env
"""

    if "PostgreSQL" in services:
        compose += """
  postgres:
    image: postgres:17
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: password
      POSTGRES_DB: app_development
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
"""

    if "MySQL/MariaDB" in services:
        compose += """
  db:
    image: mariadb:11
    environment:
      MARIADB_ROOT_PASSWORD: password
      MARIADB_DATABASE: app_development
      MARIADB_USER: app
      MARIADB_PASSWORD: password
    ports:
      - "3306:3306"
    volumes:
      - mariadb_data:/var/lib/mysql
"""

    if "MongoDB" in services:
        compose += """
  mongo:
    image: mongo:8
    ports:
      - "27017:27017"
    volumes:
      - mongo_data:/data/db
"""

    if "Redis" in services or "Sidekiq" in services:
        compose += """
  redis:
    image: redis:7
    ports:
      - "6379:6379"
"""

    if "Sidekiq" in services:
        compose += """
  sidekiq:
    build: .
    command: bundle exec sidekiq
    env_file:
      - .env
    depends_on:
      - redis
"""

    volumes = []

    if "PostgreSQL" in services:
        volumes.append("postgres_data")

    if "MySQL/MariaDB" in services:
        volumes.append("mariadb_data")

    if "MongoDB" in services:
        volumes.append("mongo_data")

    if volumes:
        compose += "\nvolumes:\n"
        for volume in volumes:
            compose += f"  {volume}:\n"

    return compose


def get_run_command():
    return "docker compose up --build"


def generate_docker_files(path: str, analysis: dict):
    repo_path = Path(path).resolve()

    dockerfile_path = repo_path / "Dockerfile"
    dockerignore_path = repo_path / ".dockerignore"
    compose_path = repo_path / "docker-compose.yml"

    created = []

    dockerfile = choose_dockerfile(analysis)

    if dockerfile and not dockerfile_path.exists():
        dockerfile_path.write_text(dockerfile)
        created.append("Dockerfile")

    if not dockerignore_path.exists():
        dockerignore_path.write_text(DOCKERIGNORE)
        created.append(".dockerignore")

    if not compose_path.exists():
        compose_path.write_text(generate_compose(analysis))
        created.append("docker-compose.yml")

    return {
        "created": created,
        "run_command": get_run_command(),
    }