from pathlib import Path


PYTHON_DOCKERFILE = """FROM python:3.12-slim

WORKDIR /app

COPY . .

RUN pip install -e .

CMD ["python", "--version"]
"""

NODE_DOCKERFILE = """FROM node:22

WORKDIR /app

COPY package*.json ./

RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "start"]
"""

RUBY_DOCKERFILE = """FROM ruby:3.2

WORKDIR /app

RUN apt-get update -qq && apt-get install -y build-essential libpq-dev nodejs

COPY Gemfile Gemfile.lock ./

RUN bundle install

COPY . .

EXPOSE 3000

CMD ["rails", "server", "-b", "0.0.0.0"]
"""

PYTHON_COMPOSE = """services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
"""

NODE_COMPOSE = """services:
  app:
    build: .
    ports:
      - "3000:3000"
    env_file:
      - .env
"""

RUBY_COMPOSE = """services:
  app:
    build: .
    ports:
      - "3000:3000"
    env_file:
      - .env
"""

DOCKERIGNORE = """.venv
__pycache__
*.pyc
node_modules
.git
.env
log
tmp
"""


def choose_stack(detected: list[str]) -> str:
    if "Node.js app" in detected:
        return "node"

    if "Ruby app" in detected or "Rails app" in detected:
        return "ruby"

    if "Python app" in detected or "Django app" in detected:
        return "python"

    return "unknown"


def generate_docker_files(path: str, analysis: dict):
    repo_path = Path(path).resolve()

    dockerfile_path = repo_path / "Dockerfile"
    dockerignore_path = repo_path / ".dockerignore"
    compose_path = repo_path / "docker-compose.yml"

    created = []
    detected = analysis.get("detected", [])
    stack = choose_stack(detected)

    if stack == "node":
        dockerfile_content = NODE_DOCKERFILE
        compose_content = NODE_COMPOSE
    elif stack == "ruby":
        dockerfile_content = RUBY_DOCKERFILE
        compose_content = RUBY_COMPOSE
    elif stack == "python":
        dockerfile_content = PYTHON_DOCKERFILE
        compose_content = PYTHON_COMPOSE
    else:
        return created

    if not dockerfile_path.exists():
        dockerfile_path.write_text(dockerfile_content)
        created.append("Dockerfile")

    if not dockerignore_path.exists():
        dockerignore_path.write_text(DOCKERIGNORE)
        created.append(".dockerignore")

    if not compose_path.exists():
        compose_path.write_text(compose_content)
        created.append("docker-compose.yml")

    return created