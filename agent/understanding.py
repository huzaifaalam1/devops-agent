"""Static evidence and conservative eligibility for the first supported workflow.

Never execute project configuration. Environment values are used only to determine
whether a documented variable is supplied and never enter the returned report.
"""

import json
import re
import shlex
from pathlib import Path

MAX_METADATA_BYTES = 2 * 1024 * 1024
SERVICE_PACKAGES = {
    "pg": "PostgreSQL", "postgres": "PostgreSQL", "@prisma/client": "Database (Prisma)",
    "mysql2": "MySQL/MariaDB", "mongoose": "MongoDB", "mongodb": "MongoDB",
    "redis": "Redis", "ioredis": "Redis", "bull": "Background jobs", "bullmq": "Background jobs",
    "@supabase/supabase-js": "Supabase/PostgreSQL", "firebase": "Firebase",
    "firebase-admin": "Firebase", "aws-sdk": "AWS Services",
    "better-sqlite3": "SQLite", "sqlite3": "SQLite",
}


def read_text(root, relative):
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"{relative}: points outside the selected application directory")
    if path.stat().st_size > MAX_METADATA_BYTES:
        raise ValueError(f"{relative}: exceeds the 2 MiB inspection limit")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeError:
        raise ValueError(f"{relative}: is not valid UTF-8") from None


def read_json(root, relative):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{relative}: contains duplicate JSON keys")
            result[key] = value
        return result
    try:
        data = json.loads(read_text(root, relative), object_pairs_hook=unique)
    except json.JSONDecodeError:
        raise ValueError(f"{relative}: is not valid JSON") from None
    if not isinstance(data, dict):
        raise ValueError(f"{relative}: must contain a JSON object")
    return data


def dependencies(package):
    result = {}
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        values = package.get(section, {})
        if not isinstance(values, dict) or any(not isinstance(v, str) for v in values.values()):
            raise ValueError(f"package.json: {section} must map package names to version strings")
        for name, version in values.items():
            if name in result and result[name][0] != version:
                raise ValueError("package.json: dependency sections contain conflicting versions")
            result[name] = (version, section)
    return result


def node22_support(spec):
    """Support a conservative subset of npm ranges covering the entire Node 22 line.

    Partial patch/minor requirements are unknown because the generator uses a
    floating node:22 image. This intentionally isn't a general semver evaluator.
    """
    if not isinstance(spec, str):
        return "unknown"
    spec = spec.strip()
    if spec in ("22", "22.x", "22.*", "^22.0.0", "*", ">=22", ">=22.0.0"):
        return "compatible"
    if re.fullmatch(r"(?:\^)?\d+(?:\.(?:\d+|x|\*)){0,2}", spec):
        major = int(re.match(r"\^?(\d+)", spec)[1])
        return "incompatible" if major != 22 else "unknown"
    terms = spec.split()
    if not terms:
        return "unknown"
    matches = [re.fullmatch(r"(>=|>|<=|<)(\d+)(?:\.(\d+))?(?:\.(\d+))?", term) for term in terms]
    if not all(matches):
        return "unknown"
    lower, upper = (22, 0, 0), (22, 999999, 999999)
    def accepts(version, match):
        bound = tuple(int(match[i] or 0) for i in (2, 3, 4))
        return {">=": version >= bound, ">": version > bound,
                "<=": version <= bound, "<": version < bound}[match[1]]
    if all(accepts(lower, m) and accepts(upper, m) for m in matches):
        return "compatible"
    # Do not infer incompatibility from contradictory or partially understood ranges.
    if any((m[1] in (">", ">=") and int(m[2]) > 22) or
           (m[1] == "<" and (int(m[2]), int(m[3] or 0), int(m[4] or 0)) <= lower) or
           (m[1] == "<=" and int(m[2]) < 22) for m in matches):
        return "incompatible"
    return "unknown"


def inspect_project(repo_info):
    root = Path(repo_info["path"])
    findings, blockers, assumptions, unknowns = [], [], [], []
    def fact(name, value, source, field=None, certainty="confirmed"):
        evidence = {"path": source}
        if field:
            evidence["field"] = field
        findings.append({"name": name, "value": value, "certainty": certainty, "evidence": [evidence]})
    def block(code, message, source, action, uncertain=False):
        blockers.append({"code": code, "message": message, "evidence": [{"path": source}],
                         "next_action": action, "needs_input": uncertain})
    def load(name):
        try:
            return read_json(root, name)
        except (OSError, ValueError) as error:
            block("invalid_metadata", str(error) if isinstance(error, ValueError) else f"Cannot read {name}.",
                  name, f"Repair or make {name} readable and analyze again.")
            return {}

    candidates = [str(Path(c["path"]).relative_to(root)) for c in repo_info.get("components", [])]
    if candidates:
        block("application_selection", "Additional application directories were found.", ".",
              "Which application should be inspected? Run the command with one of: " + ", ".join(candidates), True)
    package = load("package.json") if "package.json" in repo_info["found_files"] else {}
    try:
        deps = dependencies(package)
    except ValueError as error:
        block("invalid_dependencies", str(error), "package.json", "Repair dependency declarations.")
        deps = {}
    if "next" not in deps:
        block("unsupported_framework", "No declared Next.js dependency was found.", "package.json",
              "Select a single Next.js application using npm; other stacks are analysis-only.")
    else:
        fact("framework", "Next.js", "package.json", deps["next"][1] + ".next")
    if package.get("workspaces"):
        block("workspaces", "npm workspaces require application selection.", "package.json",
              "Select an independently installable application directory.", True)
    for marker in ("Gemfile", "manage.py", "requirements.txt", "pyproject.toml"):
        if marker in repo_info["found_files"] and "next" in deps:
            block("mixed_stack", "Multiple runtime manifests exist in this application directory.", marker,
                  "Identify the intended standalone Next.js application.", True)

    managers = set()
    for filename, manager in (("package-lock.json", "npm"), ("yarn.lock", "yarn"),
                              ("pnpm-lock.yaml", "pnpm"), ("bun.lock", "bun"), ("bun.lockb", "bun")):
        if (root / filename).exists():
            managers.add(manager)
            fact("package_manager", manager, filename, certainty="inferred")
    declared = package.get("packageManager")
    if declared is not None:
        if not isinstance(declared, str) or not re.fullmatch(r"(?:npm|yarn|pnpm|bun)@[^\s]+", declared):
            block("package_manager", "Unrecognized packageManager declaration.", "package.json", "Declare a supported npm package manager.", True)
        else:
            manager = declared.split("@", 1)[0]
            managers.add(manager)
            fact("package_manager", manager, "package.json", "packageManager")
    if managers != {"npm"}:
        block("package_manager", "Package-manager evidence is missing, unsupported, or conflicting.", "package.json",
              "Use npm with package-lock.json; resolve conflicting manager declarations/lockfiles.", len(managers) > 1)

    lock = load("package-lock.json") if (root / "package-lock.json").exists() else {}
    if not lock:
        block("missing_lockfile", "A readable package-lock.json is required.", "package-lock.json", "Generate and review an npm lockfile before dockerizing.")
    else:
        lock_root = lock.get("packages", {}).get("") if isinstance(lock.get("packages"), dict) else None
        if lock.get("lockfileVersion") not in (2, 3) or not isinstance(lock_root, dict):
            block("lockfile_format", "The lockfile must have v2/v3 root package metadata.", "package-lock.json", "Regenerate the lockfile using npm.")
        elif any(package.get(key, {}) != lock_root.get(key, {}) for key in ("dependencies", "devDependencies", "optionalDependencies", "engines")):
            block("lockfile_mismatch", "Manifest and lockfile root declarations disagree.", "package-lock.json", "Synchronize package.json and its npm lockfile.")
        else:
            fact("lockfile", "Root declarations match package.json", "package-lock.json", "packages['']")
            unknowns.append("Transitive lockfile integrity and installability require npm validation.")

    engines = package.get("engines", {})
    engine = engines.get("node") if isinstance(engines, dict) else None
    if engine is None:
        block("unknown_runtime", "No Node engine requirement is declared.", "package.json", "Declare engines.node compatible with the Node 22 image.", True)
    else:
        compatibility = node22_support(engine)
        fact("runtime", "Node requirement is " + compatibility + " with the Node 22 image", "package.json", "engines.node")
        if compatibility != "compatible":
            block("runtime", "The Node requirement is incompatible or cannot be verified for the floating Node 22 image.",
                  "package.json", "Resolve the runtime requirement; supported range syntax is documented in docs/repository-understanding.md.", compatibility == "unknown")
    for filename in (".nvmrc", ".node-version"):
        if (root / filename).exists():
            try:
                declared_version = read_text(root, filename).strip().removeprefix("v")
                if node22_support(declared_version) != "compatible":
                    block("runtime_conflict", "Runtime-file evidence does not establish Node 22 compatibility.", filename,
                          "Resolve the runtime file and engines.node requirement together.", True)
                else:
                    fact("runtime", "Node 22 compatible", filename)
            except (OSError, ValueError):
                block("runtime_file", "Cannot inspect runtime file.", filename, "Make the runtime file readable.")

    scripts = package.get("scripts", {})
    dev = scripts.get("dev") if isinstance(scripts, dict) else None
    startup = None
    try:
        tokens = shlex.split(dev) if isinstance(dev, str) else []
    except ValueError:
        tokens = []
    if tokens[:2] != ["next", "dev"]:
        block("startup", "Cannot establish a direct next dev startup command.", "package.json", "Declare scripts.dev as a direct next dev command, or clarify custom startup requirements.", True)
    else:
        startup = "npm run dev"
        fact("startup_command", startup, "package.json", "scripts.dev")
        port, host = "3000", "0.0.0.0"
        arguments = tokens[2:]
        while arguments:
            token = arguments.pop(0)
            if token in ("--turbo", "--turbopack", "--webpack"):
                continue
            if "=" in token:
                flag, value = token.split("=", 1)
            else:
                flag, value = token, arguments.pop(0) if arguments else ""
            if flag in ("--port", "-p") and value.isdigit():
                port = value
            elif flag in ("--hostname", "-H") and value in ("0.0.0.0", "::", "localhost", "127.0.0.1"):
                host = value
            else:
                block("startup_options", "Startup uses options or commands that cannot be statically verified.", "package.json", "Clarify startup options; the first workflow supports direct next dev on port 3000.", True)
                break
        fact("application_port", port, "package.json", "scripts.dev", "inferred")
        if port != "3000" or host not in ("0.0.0.0", "::"):
            block("startup_binding", "Startup binding differs from the generated container's port-3000 interface.", "package.json", "Resolve the startup binding before using the current Docker template.")
        if scripts.get("predev") or scripts.get("postdev"):
            block("startup_hooks", "npm startup hooks introduce additional commands.", "package.json", "Review predev/postdev requirements before generation.", True)
        assumptions.append("Absent explicit flags, next dev is assumed to listen on port 3000 on all interfaces; runtime validation is still required.")

    services = []
    for name, (_, section) in deps.items():
        service = SERVICE_PACKAGES.get(name) or ("AWS Services" if name.startswith("@aws-sdk/") else None)
        if service:
            services.append(service)
            fact("service_dependency", service, "package.json", section + "." + name, "inferred")
            block("service_dependency", f"Dependency evidence suggests {service}; it does not prove a running service is required.",
                  "package.json", "Clarify/remove the dependency or defer this app until service-backed workflows are supported.", True)

    # Blank example entries mean unresolved documented configuration, not proven
    # mandatory runtime variables. Do not read or return their literal values.
    supplied, documented, seen = set(), set(), set()
    for filename in (".env.development.local", ".env.local", ".env.development", ".env", ".env.example"):
        if not (root / filename).exists():
            continue
        try:
            text = read_text(root, filename)
        except (OSError, ValueError):
            block("environment_unreadable", "Environment file could not be inspected.", filename, "Make this file readable without sharing its values.", True)
            continue
        for line in text.splitlines():
            match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", line)
            if not match:
                continue
            name, value = match.groups()
            if filename == ".env.example":
                documented.add(name)
                fact("documented_variable", name, filename, certainty="confirmed")
            elif name not in seen:
                seen.add(name)
                # Simple single-line dotenv values only; complex syntax stays unresolved.
                value = value.strip()
                if value.startswith(('"', "'")):
                    quoted = re.fullmatch(r"(['\"])(.*?)\1\s*(?:#.*)?", value)
                    value = quoted[2] if quoted else ""
                else:
                    value = value.split("#", 1)[0].strip()
                if value and "$" not in value:
                    supplied.add(name)
                    fact("provided_variable", name, filename)
    for filename in ("next.config.js", "next.config.mjs", "next.config.ts"):
        if not (root / filename).exists():
            continue
        try:
            config = read_text(root, filename)
        except (OSError, ValueError):
            block("config_unreadable", "Next configuration cannot be inspected.", filename, "Make configuration readable.", True)
            continue
        for name in sorted(set(re.findall(r"process\.env\.([A-Za-z_][A-Za-z0-9_]*)", config))):
            fact("referenced_variable", name, filename, certainty="inferred")
        guarded = re.findall(r"if\s*\(\s*!process\.env\.([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*\{?\s*throw\b", config)
        for name in sorted(set(guarded) - supplied):
            block("environment_guard", f"Static configuration suggests a required variable: {name}.", filename,
                  f"Provide {name} locally or clarify the guard; configuration has not been executed.", True)
        if re.search(r"process\.env\s*\[", config):
            block("dynamic_environment", "Configuration uses dynamic environment access.", filename,
                  "Document required variable names in .env.example and review dynamic configuration.", True)
    for name in sorted(documented - supplied):
        block("environment_missing", f"Documented variable {name} has no nonempty value in inspected environment files.", ".env.example",
              f"Provide {name} locally or clarify whether it is optional; values will not be printed.", True)
    if "PORT" in seen and tokens[:2] == ["next", "dev"] and not any(t in ("--port", "-p") or t.startswith("--port=") for t in tokens):
        block("environment_port", "A dotenv PORT declaration can affect the assumed startup port.", ".env*",
              "Declare an explicit port-3000 startup flag or review the environment port override.", True)
    unknowns.append("Environment inspection covers named development dotenv files, .env.example and simple Next config references only. Config matches are heuristic; arbitrary source, host variables and Docker environment wiring are not evaluated.")

    dockerfiles, compose = repo_info["dockerfiles"], repo_info["compose_files"]
    setup = "none"
    if dockerfiles or compose:
        setup = "existing" if dockerfiles and compose else "partial"
        if setup == "partial":
            block("partial_setup", "Docker setup is incomplete: both Dockerfile and Compose are required for this workflow.",
                  (dockerfiles or compose)[0], "Complete or review the existing setup; no files will be overwritten.")
        if len(dockerfiles) > 1 or len(compose) > 1:
            setup = "ambiguous"
            block("compose_selection", "Multiple Docker/Compose variants require explicit selection.", ".", "Select a directory with one intended Dockerfile and Compose file.", True)
        for filename in dockerfiles + compose:
            fact("existing_infrastructure", "Reuse candidate; compatibility unverified", filename)
            try:
                text = read_text(root, filename)
            except (OSError, ValueError):
                block("infrastructure_unreadable", "Cannot inspect this infrastructure file.", filename, "Make the selected file readable.", True)
                continue
            if filename in dockerfiles:
                for tag in re.findall(r"^\s*FROM\s+(?:--platform=\S+\s+)?node:([^\s@]+)", text, re.MULTILINE | re.IGNORECASE):
                    major = re.match(r"(\d+)(?:[.-]|$)", tag)
                    if major and int(major[1]) != 22:
                        block("docker_runtime_conflict", "Existing Dockerfile declares a Node image outside the Node 22 target.", filename,
                              "Resolve Dockerfile and package runtime requirements together.", True)
        unknowns.append("Existing Docker/Compose contents require configuration and runtime validation; file presence alone proves neither compatibility nor readiness.")
    status = "eligible" if not blockers else ("needs_input" if any(b["needs_input"] for b in blockers) else "blocked")
    return {"eligibility": status, "findings": findings, "blockers": blockers,
            "assumptions": assumptions, "unknowns": unknowns, "application_candidates": candidates,
            "setup": setup, "startup_command": startup, "services": sorted(set(services)),
            "scope": "Single Next.js application, npm, Node 22, local development; eligibility is not readiness."}
