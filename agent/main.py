from typing import Annotated

import json
import os
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
from agent.repair import propose_repair, apply_repair
from agent.planning import advise as model_advice


app = typer.Typer()
console = Console()

@app.command()
def chat(
    path: Annotated[str | None, typer.Argument(help="Application directory; prompts when omitted")] = None,
    offline: Annotated[bool, typer.Option("--offline", help="Use the read-only shell without model or persistence")] = False,
    resume: Annotated[str | None, typer.Option("--resume", help="Resume a conversation belonging to this repository")] = None,
):
    """Start an interactive agent session, or the offline inspection shell."""
    def read(prompt):
        return input(prompt + "> ")
    emit = lambda message: console.print(message, markup=False, highlight=False)
    if offline:
        if resume:
            raise typer.BadParameter("--resume requires the persistent session, not --offline.")
        from agent.session import run_session
        run_session(path, read, emit)
    else:
        from agent.conversation import run_chat
        run_chat(path, read, emit, resume=resume)


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


def choose_compose_file(repo_info, requested=None):
    """Select a discovered root file without following symlinks or guessing variants."""
    files = repo_info["compose_files"]
    if requested is None:
        if len(files) > 1:
            raise ValueError("Multiple Compose files found; select one with --compose-file FILE.")
        return files[0] if files else None
    candidate = Path(requested)
    root = Path(repo_info["path"]).resolve()
    if (candidate.is_absolute() or len(candidate.parts) != 1 or requested not in files
            or (root / requested).is_symlink() or not (root / requested).is_file()
            or not (root / requested).resolve().is_relative_to(root)):
        raise ValueError("--compose-file must name a discovered regular Compose file in the application root; symlinks and outside paths are refused.")
    return requested


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

def validation_result(path, compose_file=None, existing_setup=False, build=False, run=False,
                      keep_running=False, service=None, container_port=None, health_path="/",
                      timeout=300, readiness_timeout=90):
    """Shared CLI/tool policy path; never bypass eligibility or isolation."""
    repo_info, analysis = inspect_repo(path)
    try:
        if existing_setup and compose_file is None:
            raise ValueError("--existing-setup requires an explicit --compose-file selection.")
        selected = choose_compose_file(repo_info, compose_file)
        if compose_file is not None:
            repo_info["selected_compose_file"] = selected
            analysis = detect_stack(repo_info)
    except ValueError as error:
        result = {"success": False, "phase": "selection", "error": str(error)}
        return result
    project = analysis["project"]
    deferred = []
    blocking = project["blockers"]
    if existing_setup:
        # These checks constrain our generated runtime template, not a reviewed
        # existing Dockerfile. Build/runtime outcomes remain independently checked.
        template_codes = {"package_manager", "unknown_runtime", "runtime", "runtime_conflict", "docker_runtime_conflict"}
        # Package dependency hints and example dotenv entries do not establish
        # actual runtime requirements. Only a full runtime check may defer them:
        # resolved Compose, service health and application readiness still apply.
        if run:
            template_codes |= {"service_dependency", "environment_missing"}
        deferred = [item for item in blocking if item["code"] in template_codes]
        blocking = [item for item in blocking if item["code"] not in template_codes]
    if (build or run) and blocking:
        result = {"success": False, "phase": "eligibility", "project": analysis["project"],
                  "error": "Repository is not eligible for build/runtime validation.", "blockers": blocking}
    elif not repo_info["compose_files"]:
        result = {"success": False, "phase": "config", "error": "No Docker Compose file was found."}
    else:
        result = validate_docker(path, compose_file=selected,
                                 build=build, run=run, keep_running=keep_running, service=service,
                                 container_port=container_port, health_path=health_path, timeout=timeout,
                                 readiness_timeout=readiness_timeout)
    if existing_setup:
        result["eligibility_basis"] = {"mode": "existing_setup", "compose_file": selected,
            "deferred_template_checks": deferred,
            "notice": "Selected Compose configuration, build and readiness checks establish only the tested runtime behavior. Dependency hints and example dotenv entries may be deferred for --run; required-variable guards and isolation checks remain mandatory."}
        if any(item["code"] in {"service_dependency", "environment_missing"} for item in deferred):
            result.setdefault("unverified", []).append("All environment-dependent paths and service-backed business operations; HTTP readiness alone does not verify database transactions.")
    result = Redactor(path).clean(result)
    if not result["success"]:
        result["diagnosis"] = diagnose_failure(result)
    return result


@app.command()
def validate(
    path: Annotated[str, typer.Argument(help="Path to the repo")] = ".",
    compose_file: Annotated[str | None, typer.Option("--compose-file", help="Select one root Compose file; does not override isolation checks")] = None,
    existing_setup: Annotated[bool, typer.Option("--existing-setup", help="Use the selected existing Next.js Docker setup to establish runtime, environment and service readiness instead of the generation template")] = False,
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
    result = validation_result(path, compose_file, existing_setup, build, run, keep_running,
                               service, container_port, health_path, timeout, readiness_timeout)
    if json_output:
        typer.echo(json.dumps(result, indent=2))
    else:
        console.print(Panel.fit("Docker validation", style="bold cyan"))
        console.print(("Passed: " if result["success"] else "Failed: ") + result["phase"], markup=False)
        if result.get("session_id"):
            console.print("Session: " + result["session_id"], markup=False)
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
def advise(
    path: Annotated[str, typer.Argument(help="Application directory")],
    model: Annotated[str | None, typer.Option(help="Override .env/environment model; default depends on provider")] = None,
    session: Annotated[str | None, typer.Option("--session", help="Optional current runtime validation session")] = None,
    send: Annotated[bool, typer.Option("--send", help="Send the reviewed sanitized request to the selected provider; grants no execution authority")] = False,
    expect: Annotated[str | None, typer.Option("--expect", help="Required reviewed request ID when sending")] = None,
    max_output_tokens: Annotated[int, typer.Option("--max-output-tokens", min=256, max=4096)] = 2000,
    input_rate: Annotated[float | None, typer.Option("--input-rate", min=0, help="Optional USD per million input tokens for estimation")] = None,
    output_rate: Annotated[float | None, typer.Option("--output-rate", min=0, help="Optional USD per million output tokens for estimation")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
):
    """Preview model evidence; --send requires its exact reviewed ID."""
    try:
        result = model_advice(path, model, session=session,
                              send=send, expect=expect, max_output_tokens=max_output_tokens,
                              input_rate=input_rate, output_rate=output_rate)
        if json_output:
            typer.echo(json.dumps(result, indent=2))
        elif not send:
            console.print("Model request preview: " + result['request']['model'], markup=False)
            console.print("Destination: " + result['endpoint'], markup=False)
            console.print(result['notice'], markup=False)
            bundle = json.loads(result['request']['input'][0]['content'])
            for fact in bundle['facts']:
                console.print(f"{fact['id']} [{fact['source']}]: " + json.dumps(fact['value']), markup=False)
            for action in bundle['actions']:
                console.print(action['id'] + ": " + action['description'], markup=False)
            console.print("Request ID: " + result['id'], markup=False)
            console.print("Use --json to inspect the complete request; --send --expect ID sends it with the bounded retry policy.", markup=False)
        else:
            console.print("Unverified model advice: " + result['status'], markup=False)
            for hypothesis in result.get('plan', {}).get('hypotheses', []):
                console.print("Hypothesis: " + hypothesis['text'] + " [" + ', '.join(hypothesis['evidence_ids']) + "]", markup=False)
            for step in result.get('plan', {}).get('steps', []):
                console.print("Proposed " + step['action_id'] + ": " + step['reason'], markup=False)
            for uncertainty in result.get('plan', {}).get('uncertainties', []):
                console.print("Limit: " + uncertainty, markup=False)
            if result.get('error'):
                console.print(result['error'], markup=False)
            console.print("Deterministic baseline: " + result['baseline']['description'], markup=False)
            console.print("Actions executed: 0. " + result['notice'], markup=False)
            console.print("Metrics: " + json.dumps(result['metrics']), markup=False)
        if send and not result['success']:
            raise typer.Exit(130 if result['status'] == 'cancelled' else 1)
    except (OSError, ValueError, KeyError) as error:
        message = Redactor(path).text(str(error))
        typer.echo(json.dumps({'success': False, 'status': 'refused', 'error': message}) if json_output else message)
        raise typer.Exit(1) from None


@app.command()
def repair(
    path: Annotated[str, typer.Argument(help="Application directory")],
    session: Annotated[str, typer.Option("--session", help="Failed runtime validation session ID")],
    host_port: Annotated[int | None, typer.Option("--host-port", min=1024, max=65535)] = None,
    health_path: Annotated[str | None, typer.Option("--health-path", help="Existing unauthenticated readiness route")] = None,
    apply: Annotated[bool, typer.Option("--apply", help="Authorize the reviewed repair and one runtime verification")] = False,
    expect: Annotated[str | None, typer.Option("--expect", help="Required reviewed proposal ID when applying")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
):
    """Preview a supported repair; apply only after reviewing its exact ID."""
    try:
        plan = propose_repair(path, session, host_port=host_port, health_path=health_path)
        if expect is not None and not apply:
            raise ValueError("--expect requires --apply.")
        result = apply_repair(plan, expect) if apply else plan
        if json_output:
            typer.echo(json.dumps(result, indent=2))
        else:
            console.print("Repair: " + result['status'], markup=False)
            if not apply:
                if plan.get('diagnosis'):
                    console.print(plan['diagnosis']['summary'], markup=False)
                for key in ('summary', 'impact', 'verification', 'approval'):
                    if plan.get(key):
                        console.print(plan[key], markup=False)
                for change in plan['changes']:
                    console.print(change['diff'], markup=False, highlight=False)
                for blocker in plan['blockers']:
                    console.print("Blocked: " + blocker, markup=False)
                if plan['status'] == 'blocked' and plan.get('diagnosis'):
                    console.print("Manual action: " + plan['diagnosis']['suggested_actions'][0], markup=False)
                if plan.get('id'):
                    console.print("Proposal ID: " + plan['id'], markup=False)
                console.print("Attempt limit: 1. Preview performs no repair or Docker execution.", markup=False)
            else:
                console.print("Session: " + result['session_id'], markup=False)
                console.print("Attempts: " + str(result['attempts']), markup=False)
                console.print("Rollback: " + result['rollback']['status'], markup=False)
                for key in ('summary', 'error', 'next_action'):
                    if result.get(key):
                        console.print(result[key], markup=False)
                if result.get('diagnosis'):
                    console.print("Diagnosis: " + result['diagnosis']['summary'], markup=False)
                    console.print("Manual action: " + result['diagnosis']['suggested_actions'][0], markup=False)
                if result.get('validation'):
                    console.print("Validation: " + result['validation']['phase'], markup=False)
                    console.print("Cleanup: " + result['validation'].get('cleanup', {}).get('status', 'unknown'), markup=False)
                    check = result['validation'].get('application_check') or {}
                    if check.get('url'):
                        console.print("Checked endpoint: " + check['url'], markup=False)
                console.print("Use --json for full sanitized evidence; successful runs are stopped after verification.", markup=False)
        if (apply and not result['success']) or (not apply and result['status'] != 'ready'):
            raise typer.Exit(130 if result.get('status') == 'cancelled' else 1)
    except (OSError, ValueError, KeyError, TypeError) as error:
        message = Redactor(path).text(str(error))
        if json_output:
            typer.echo(json.dumps({'success': False, 'status': 'refused', 'error': message}))
        else:
            console.print("Repair refused: " + message, markup=False)
        raise typer.Exit(1) from None


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
