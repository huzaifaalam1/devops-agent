"""Materialize immutable fixture sources into disposable directories."""

import argparse
import json
import shutil
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
CASES = json.loads((FIXTURES / "cases.json").read_text())


def materialize(case: str, destination: Path) -> Path:
    if case not in {item["id"] for item in CASES}:
        raise ValueError(f"Unknown fixture: {case}")
    # Never overwrite an existing checkout, including another materialized fixture.
    destination.mkdir(parents=True, exist_ok=False)
    if case == "unsupported":
        shutil.copytree(FIXTURES / "unsupported", destination, dirs_exist_ok=True)
        return destination
    if case == "multi-component":
        for component in ("frontend", "backend"):
            shutil.copytree(FIXTURES / "next-app", destination / component)
        return destination
    shutil.copytree(FIXTURES / "next-app", destination, dirs_exist_ok=True)
    if case in {"existing-compose", "port-conflict", "missing-env", "startup-failure"}:
        shutil.copytree(FIXTURES / "existing-compose", destination, dirs_exist_ok=True)
    if case in {"missing-env", "startup-failure", "database"}:
        shutil.copytree(FIXTURES / case, destination, dirs_exist_ok=True)
    if case == "partial-docker":
        shutil.copyfile(FIXTURES / "existing-compose" / "Dockerfile", destination / "Dockerfile")
    if case == "incompatible-runtime":
        for filename in ("package.json", "package-lock.json"):
            path = destination / filename
            data = json.loads(path.read_text())
            root = data if filename == "package.json" else data["packages"][""]
            root["engines"]["node"] = "18.x"
            path.write_text(json.dumps(data, indent=2) + "\n")
    if case in {"missing-lockfile", "yarn"}:
        (destination / "package-lock.json").unlink()
    if case == "yarn":
        path = destination / "package.json"
        data = json.loads(path.read_text())
        data["packageManager"] = "yarn@1.22.22"
        path.write_text(json.dumps(data, indent=2) + "\n")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=[item["id"] for item in CASES])
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(materialize(args.case, args.destination))
