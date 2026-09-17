from typing import Annotated

import json
import typer
import platform
from rich.console import Console
from rich.panel import Panel
from pathlib import Path

from agent.scanner import scan_repo
from agent.detector import detect_stack
from agent.docker_generator import propose_docker_files, apply_docker_proposal
from agent.validator import validate_docker
from agent.diagnostics import diagnose_failure
from agent.safety import Redactor, recovery, history


app = typer.Typer()
console = Console()

def inspect_repo(path):
    try:
        repo_info = scan_repo(path)
        return repo_info, detect_stack(repo_info)
    except (OSError, ValueError):
        raise typer.BadParameter("Cannot inspect this path. Select an existing readable application directory.", param_hint="path") from None


def print_project(project):
    console.print("\nRepository understanding", style="bold cyan")
    console.print("Eligibility: " + project["eligibility"] + " (not runtime readiness)", markup=False)
    for finding in project["findings"]:
        evidence = finding["evidence"][0]
        source = evidence["path"] + (" :: " + evidence["field"] if evidence.get("field") else "")
        console.print(f"• {finding['name']}: {finding['value']} [{finding['certainty']}; {source}]", markup=False)
    for blocker in project["blockers"]:
        console.print(f"• {blocker['code']}: {blocker['message']} Source: {blocker['evidence'][0]['path']}", markup=False)
        console.print("  Next: " + blocker["next_action"], markup=False)
    for title in ("assumptions", "unknowns"):
        for item in project[title]:
            console.print(f"• {title}: {item}", markup=False)


def require_eligible(analysis):
    if analysis["project"]["eligibility"] != "eligible":
        print_project(analysis["project"])
        raise typer.Exit(code=1)


def choose_compose_file(compose_files: list[str]) -> str:
    filenames = {
        Path(compose_file).name: compose_file
        for compose_file in compose_files
    }

    system = platform.system()

    if system == "Darwin":
        preferred_files = [
            "local_mac.yml",
            "local_mac.yaml",
            "docker-compose.mac.yml",
            "docker-compose.mac.yaml",
            "compose.mac.yml",
            "compose.mac.yaml",
        ]
    elif system == "Linux":
        preferred_files = [
            "local_linux.yml",
            "local_linux.yaml",
        ]
    else:
        preferred_files = []

    preferred_files.extend(
        [
            "local.yml",
            "local.yaml",
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        ]
    )

    for preferred_file in preferred_files:
        if preferred_file in filenames:
            return filenames[preferred_file]

    return compose_files[0]

@app.callback()
def main():
    """DevOps Agent CLI."""
    pass


def print_analysis(repo_info, analysis, title="DevOps Agent Analysis"):
    console.print()
    console.print(Panel.fit(title, style="bold cyan"))
    console.print(f"[bold]Path:[/bold] {repo_info['path']}")

    console.print("\n[bold green]Detected[/bold green]")
    for item in analysis["detected"]:
        console.print(f"✓ {item}")

    if repo_info["dockerfiles"]:
        console.print("\n[bold green]Docker variants found[/bold green]")
        for file in repo_info["dockerfiles"]:
            console.print(f"✓ {file}")

    if repo_info["compose_files"]:
        console.print("\n[bold green]Compose variants found[/bold green]")
        for file in repo_info["compose_files"]:
            console.print(f"✓ {file}")

    if repo_info["config_files"]:
        console.print("\n[bold green]Config files found[/bold green]")
        for file in repo_info["config_files"]:
            console.print(f"✓ {file}")

    if repo_info["workflow_files"]:
        console.print("\n[bold green]GitHub Actions found[/bold green]")
        for file in repo_info["workflow_files"]:
            console.print(f"✓ {file}")

    if analysis["services"]:
        console.print("\n[bold green]Services detected[/bold green]")
        for service in analysis["services"]:
            console.print(f"✓ {service}")

    if analysis["runtime"]:
        console.print("\n[bold green]Runtime[/bold green]")
        for item in analysis["runtime"]:
            console.print(f"✓ {item}")

    if analysis["startup_commands"]:
        console.print("\n[bold green]Possible startup commands[/bold green]")
        for cmd in analysis["startup_commands"]:
            console.print(f"✓ {cmd}")

    console.print("\n[bold yellow]Missing[/bold yellow]")
    if analysis["missing"]:
        for item in analysis["missing"]:
            console.print(f"✗ {item}")
    else:
        console.print("None")

    console.print("\n[bold blue]Recommendations[/bold blue]")
    if analysis["recommendations"]:
        for item in analysis["recommendations"]:
            console.print(f"• {item}")
    else:
        console.print("None")


@app.command()
def analyze(
    path: Annotated[str, typer.Argument(help="Path to the repo")] = ".",
    json_output: Annotated[bool, typer.Option("--json", help="Emit structured findings and eligibility")] = False,
):
    """Analyze a repo and detect its stack without executing project code."""
    repo_info, analysis = inspect_repo(path)
    redactor = Redactor(path)
    analysis = redactor.clean(analysis)

    if json_output:
        typer.echo(json.dumps(redactor.clean({"schema_version": 1, "repository": repo_info, "analysis": analysis,
                               "components": [{"path": c["path"], "analysis": detect_stack(c)}
                                              for c in repo_info.get("components", [])]}), indent=2))
        return
    print_analysis(repo_info, analysis)
    print_project(analysis["project"])

    for component in repo_info.get("components", []):
        component_analysis = Redactor(component["path"]).clean(detect_stack(component))
        role = component.get("role", "component").title()

        print_analysis(
            component,
            component_analysis,
            title=f"{role} component: {component['name']}",
        )
        print_project(component_analysis["project"])


@app.command()
def dockerize(
    path: Annotated[str, typer.Argument(help="Path to the repo")] = ".",
    apply: Annotated[bool, typer.Option("--apply", help="Apply the displayed development setup proposal")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Emit the proposal as JSON")] = False,
    expect: Annotated[str | None, typer.Option("--expect", help="Require the ID of a previously reviewed proposal")] = None,
):
    """Preview Docker development setup. Use --apply to write changes."""
    try:
        proposal = propose_docker_files(path)
        redactor = Redactor(path)
        public = redactor.clean(proposal)
        if expect is not None and (not apply or proposal.get("id") != expect):
            raise ValueError("Proposal ID does not match, or --apply is missing. Review a fresh proposal.")
        if not json_output:
            console.print(Panel.fit("Docker development setup proposal", style="bold cyan"))
            console.print("Status: " + public["status"], markup=False)
            for blocker in public["blockers"]:
                console.print(blocker["code"] + ": " + blocker["message"], markup=False)
                console.print("Next: " + blocker["next_action"], markup=False)
            for change in public["changes"]:
                console.print(change["path"] + ": " + change["reason"], markup=False)
                console.print(change["diff"], markup=False, highlight=False)
            for note in public["notes"]:
                console.print(note, markup=False)
            for filename in public["preserved"]:
                console.print("Preserved: " + filename, markup=False)
            if public.get("id"):
                console.print("Proposal ID: " + public["id"], markup=False)
        if proposal["status"] == "blocked":
            if json_output:
                typer.echo(json.dumps(redactor.clean(proposal), indent=2))
            raise typer.Exit(code=1)
        if apply and proposal["status"] == "ready":
            result = apply_docker_proposal(proposal)
            proposal["applied"] = result
            if not json_output:
                console.print("Applied: " + ", ".join(result["created"] + result["updated"]), markup=False)
                console.print("Run after review: " + result["run_command"], markup=False)
                console.print("Recovery preview: " + result["recovery_command"], markup=False)
        elif not json_output and proposal["status"] == "ready":
            console.print("Preview only. Rerun with --apply --expect <proposal-id> to apply this proposal.")
        if json_output:
            typer.echo(json.dumps(redactor.clean(proposal), indent=2))
    except (OSError, ValueError) as error:
        message = str(error) if isinstance(error, ValueError) else "Could not read or write the project files. Check path, permissions, and disk space."
        message = Redactor(path).text(message)
        if json_output:
            typer.echo(json.dumps({"status": "error", "message": message}))
        else:
            console.print(message, markup=False)
        raise typer.Exit(code=1) from None

@app.command()
def validate(
    path: Annotated[str, typer.Argument(help="Path to the repo")] = ".",
    build: Annotated[bool, typer.Option(help="Verify image builds in an isolated validation project")] = False,
    run: Annotated[bool, typer.Option(help="Start isolated services and verify application readiness")] = False,
    keep_running: Annotated[bool, typer.Option("--keep-running", help="Keep only a successfully validated environment running")] = False,
    service: Annotated[str | None, typer.Option(help="Application service when more than one publishes ports")] = None,
    container_port: Annotated[int | None, typer.Option("--container-port", min=1, max=65535)] = None,
    health_path: Annotated[str, typer.Option("--health-path", help="Unauthenticated readiness path on the owned container")] = "/",
    timeout: Annotated[float, typer.Option(min=1, help="Total execution deadline in seconds, excluding bounded cleanup")] = 300,
    readiness_timeout: Annotated[float, typer.Option("--readiness-timeout", min=1)] = 90,
    json_output: Annotated[bool, typer.Option("--json", help="Emit stage, ownership and cleanup evidence")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Show redacted captured command output and service logs")] = False,
):
    """Validate configuration, builds, or isolated runtime readiness."""
    repo_info, analysis = inspect_repo(path)
    if (build or run) and analysis["project"]["eligibility"] != "eligible":
        result = {"success": False, "phase": "eligibility", "project": analysis["project"],
                  "error": "Repository is not eligible for build/runtime validation."}
    elif not repo_info["compose_files"]:
        result = {"success": False, "phase": "config", "error": "No Docker Compose file was found."}
    else:
        result = validate_docker(path, compose_file=choose_compose_file(repo_info["compose_files"]),
                                 build=build, run=run, keep_running=keep_running, service=service,
                                 container_port=container_port, health_path=health_path, timeout=timeout,
                                 readiness_timeout=readiness_timeout)
    result = Redactor(path).clean(result)
    if not result["success"]:
        result["diagnosis"] = diagnose_failure(result)
    if json_output:
        typer.echo(json.dumps(result, indent=2))
    else:
        console.print(Panel.fit("Docker validation", style="bold cyan"))
        console.print(("Passed: " if result["success"] else "Failed: ") + result["phase"], markup=False)
        for stage in result.get("stages", []):
            console.print(f"• {stage['phase']}: {stage.get('status', 'passed' if stage['success'] else 'failed')}", markup=False)
        if result.get("diagnosis"):
            diagnosis = result["diagnosis"]
            console.print("Diagnosis: " + diagnosis["summary"] + " (" + diagnosis["confidence"] + " confidence)", markup=False)
            console.print("Likely cause: " + diagnosis["likely_causes"][0], markup=False)
            for evidence in diagnosis["evidence"]:
                console.print("Evidence [" + evidence["source"] + "]: " + evidence["excerpt"], markup=False)
            console.print("Action: " + diagnosis["suggested_actions"][0], markup=False)
            console.print("Impact: " + diagnosis["expected_impact"], markup=False)
            console.print("Verify: " + diagnosis["verification"], markup=False)
            console.print(diagnosis["uncertainty"], markup=False)
            if not verbose:
                console.print(diagnosis["details_hint"], markup=False)
        if result.get("project") and isinstance(result["project"], dict):
            print_project(result["project"])
        if verbose:
            for command in result.get("results", []) + result.get("cleanup", {}).get("results", []):
                console.print("Command: " + command.get("command", "unknown"), markup=False)
                for key in ("stdout", "stderr"):
                    if command.get(key):
                        console.print(key + ": " + command[key], markup=False)
            if result.get("logs"):
                console.print("Service logs:\n" + result["logs"], markup=False)
        if result.get("error"):
            console.print(result["error"], markup=False)
        if result.get("next_action"):
            console.print("Next: " + result["next_action"], markup=False)
        check = result.get("application_check")
        if check:
            console.print(f"Endpoint: {check['url']} — HTTP {check['status_code']}", markup=False)
        if result.get("environment_state"):
            console.print("Environment: " + result["environment_state"], markup=False)
        if result.get("cleanup"):
            console.print("Cleanup: " + result["cleanup"]["status"], markup=False)
            if result["cleanup"].get("stop_command"):
                console.print("Stop later: " + result["cleanup"]["stop_command"], markup=False)
        for item in result.get("unverified", []):
            console.print("Unverified: " + item, markup=False)
    if not result["success"]:
        raise typer.Exit(code=130 if result["phase"] == "cancelled" else 1)


@app.command()
def recover(
    path: Annotated[str, typer.Argument(help="Original application directory")],
    session_id: Annotated[str, typer.Argument(help="Apply session ID")],
    apply: Annotated[bool, typer.Option("--apply", help="Restore the recorded pre-edit state")] = False,
):
    """Preview recovery; --apply restores only unchanged generated targets."""
    try:
        typer.echo(json.dumps(recovery(path, session_id, apply=apply), indent=2))
    except (OSError, ValueError, KeyError) as error:
        typer.echo(json.dumps({"success": False, "error": Redactor(path).text(str(error))}))
        raise typer.Exit(1) from None


@app.command("history")
def session_history(path: Annotated[str, typer.Argument(help="Application directory")] = "."):
    """List local action/authorization outcomes without exposing snapshots."""
    try:
        typer.echo(json.dumps(history(path), indent=2))
    except (OSError, ValueError):
        typer.echo(json.dumps({"success": False, "error": "Private session history is unavailable."}))
        raise typer.Exit(1) from None


if __name__ == "__main__":
    app()
