from typing import Annotated

import json
import typer
import platform
from rich.console import Console
from rich.panel import Panel
from pathlib import Path

from agent.scanner import scan_repo
from agent.detector import detect_stack
from agent.docker_generator import generate_docker_files
from agent.validator import (
    bring_down_compose_project,
    extract_conflicting_port,
    find_compose_project_using_port,
    validate_docker,
)
from agent.diagnostics import diagnose_failure
from agent.context import collect_diagnostic_context

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

    if json_output:
        typer.echo(json.dumps({"schema_version": 1, "repository": repo_info, "analysis": analysis,
                               "components": [{"path": c["path"], "analysis": detect_stack(c)}
                                              for c in repo_info.get("components", [])]}, indent=2))
        return
    print_analysis(repo_info, analysis)
    print_project(analysis["project"])

    for component in repo_info.get("components", []):
        component_analysis = detect_stack(component)
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
):
    """Generate Docker files for the repo."""
    repo_info, analysis = inspect_repo(path)

    require_eligible(analysis)

    if repo_info["dockerfiles"] or repo_info["compose_files"]:
        console.print()
        console.print(
            Panel.fit("Existing Docker setup preserved; compatibility unverified", style="bold cyan")
        )

        if repo_info["dockerfiles"]:
            console.print("[bold green]Docker variants found:[/bold green]")
            for file in repo_info["dockerfiles"]:
                console.print(f"✓ {file}")

        if repo_info["compose_files"]:
            console.print("\n[bold green]Compose variants found:[/bold green]")
            for file in repo_info["compose_files"]:
                console.print(f"✓ {file}")

        docker_commands = [
            cmd
            for cmd in analysis["startup_commands"]
            if "docker compose" in cmd
        ]

        if docker_commands:
            console.print("\n[bold green]Possible run commands:[/bold green]")
            for cmd in docker_commands:
                console.print(f"✓ {cmd}")

        raise typer.Exit(code=0)

    result = generate_docker_files(path, analysis)
    created = result["created"]

    console.print()
    console.print(Panel.fit("Dockerize Complete", style="bold cyan"))

    if created:
        console.print("[bold green]Created files:[/bold green]")
        for file in created:
            console.print(f"✓ {file}")
    else:
        console.print(
            "[bold yellow]No files created. Docker files already exist.[/bold yellow]"
        )

    console.print("\n[bold green]Run with:[/bold green]")
    console.print(result["run_command"])

@app.command()
def validate(
    path: Annotated[str, typer.Argument(help="Path to the repo")] = ".",
    build: Annotated[
        bool,
        typer.Option(help="Build Docker images too"),
    ] = False,
    run: Annotated[
        bool,
        typer.Option(help="Start containers and verify they remain running"),
    ] = False,
    keep_running: Annotated[
        bool,
        typer.Option(
            "--keep-running",
            help="Leave containers running after runtime validation",
        ),
    ] = False,
):
    """Validate the Docker setup for the repo."""
    repo_info, analysis = inspect_repo(path)

    if build or run:
        require_eligible(analysis)

    if not repo_info["compose_files"]:
        console.print(
            "[bold red]No Docker Compose file was found.[/bold red]"
        )
        raise typer.Exit(code=1)

    compose_file = choose_compose_file(
        repo_info["compose_files"]
    )

    result = validate_docker(
        path,
        compose_file=compose_file,
        build=build,
        run=run,
        keep_running=keep_running,
    )

    console.print()
    console.print(
        Panel.fit(
            "Docker Validation",
            style="bold cyan",
        )
    )

    console.print(
        f"[bold]Path:[/bold] {repo_info['path']}"
    )

    console.print(
        f"[bold]Compose file:[/bold] {compose_file}"
    )

    for command_result in result["results"]:
        console.print(
            f"[bold]Command:[/bold] "
            f"{command_result['command']}"
        )

    # ---------------------------------------------------------
    # Successful validation
    # ---------------------------------------------------------

    if result["success"]:

        if result["phase"] in {
            "runtime",
            "application",
        }:
            console.print(
                "\n[bold green]"
                "✓ All Docker services started successfully"
                "[/bold green]"
            )

            if result["running_services"]:
                console.print(
                    "\n[bold green]"
                    "Running services:"
                    "[/bold green]"
                )

                for service in result["running_services"]:
                    console.print(
                        f"✓ {service}"
                    )

            application_check = result.get(
                "application_check"
            )

            if application_check:
                console.print(
                    "\n[bold cyan]"
                    "Application URL discovery:"
                    "[/bold cyan]"
                )

                for candidate in application_check.get(
                    "candidates",
                    [],
                ):
                    console.print(
                        f"• {candidate}"
                    )

                console.print(
                    "\n[bold green]"
                    "✓ Application responded successfully"
                    "[/bold green]"
                )

                console.print(
                    f"[bold]URL:[/bold] "
                    f"{application_check['url']}"
                )

                console.print(
                    f"[bold]HTTP status:[/bold] "
                    f"{application_check['status_code']}"
                )

        elif result["phase"] == "build":
            console.print(
                "\n[bold green]"
                "✓ Docker images built successfully"
                "[/bold green]"
            )

        else:
            console.print(
                "\n[bold green]"
                "✓ Docker Compose configuration is valid"
                "[/bold green]"
            )

        return

    # ---------------------------------------------------------
    # Docker engine / storage failure
    # ---------------------------------------------------------

    if result["phase"] == "docker_engine":
        console.print(
            "\n[bold red]"
            "✗ Docker engine/storage error"
            "[/bold red]"
        )

        application_check = (
            result.get("application_check")
            or {}
        )

        error = application_check.get("error")

        if error:
            console.print(
                f"\n{error}",
                markup=False,
            )

        console.print(
            "\n[bold yellow]"
            "Try restarting Docker Desktop and "
            "retrying validation."
            "[/bold yellow]"
        )

        if result["logs"]:
            console.print(
                "\n[bold]Docker output:[/bold]"
            )

            console.print(
                result["logs"],
                markup=False,
            )

        raise typer.Exit(code=1)

    # ---------------------------------------------------------
    # Generic validation failure
    # ---------------------------------------------------------

    console.print(
        f"\n[bold red]"
        f"✗ Docker validation failed during "
        f"{result['phase']}"
        f"[/bold red]"
    )

    last_result = result["results"][-1]

    # ---------------------------------------------------------
    # Startup failure / port conflict handling
    # ---------------------------------------------------------

    if result["phase"] == "startup":
        error_output = (
            last_result["stderr"]
            or last_result["stdout"]
            or ""
        )

        conflicting_port = extract_conflicting_port(
            error_output
        )

        if conflicting_port is not None:
            conflict = find_compose_project_using_port(
                conflicting_port,
                Path(path).resolve(),
            )

            if conflict:
                console.print(
                    f"\n[bold yellow]"
                    f"Port {conflicting_port} "
                    f"is being used by "
                    f"{conflict['container_name']}."
                    f"[/bold yellow]"
                )

                console.print(
                    f"Compose project: "
                    f"[bold]"
                    f"{conflict['project_name']}"
                    f"[/bold]"
                )

                should_stop = typer.confirm(
                    (
                        f"Bring down "
                        f"{conflict['project_name']} "
                        f"and retry?"
                    ),
                    default=False,
                )

                if should_stop:
                    down_result = (
                        bring_down_compose_project(
                            conflict
                        )
                    )

                    if not down_result["success"]:
                        console.print(
                            "\n[bold red]"
                            "✗ Failed to bring down "
                            "the conflicting Compose project"
                            "[/bold red]"
                        )

                        console.print(
                            (
                                down_result["stderr"]
                                or down_result["stdout"]
                            ),
                            markup=False,
                        )

                        raise typer.Exit(code=1)

                    console.print(
                        f"\n[bold green]"
                        f"✓ Brought down "
                        f"{conflict['project_name']}"
                        f"[/bold green]"
                    )

                    console.print(
                        "\n[bold cyan]"
                        "Retrying Docker validation..."
                        "[/bold cyan]"
                    )

                    result = validate_docker(
                        path,
                        compose_file=compose_file,
                        build=build,
                        run=run,
                        keep_running=keep_running,
                    )

                    if result["success"]:
                        console.print(
                            "\n[bold green]"
                            "✓ All Docker services "
                            "started successfully"
                            "[/bold green]"
                        )

                        if result["running_services"]:
                            console.print(
                                "\n[bold green]"
                                "Running services:"
                                "[/bold green]"
                            )

                            for service in result[
                                "running_services"
                            ]:
                                console.print(
                                    f"✓ {service}"
                                )

                        application_check = (
                            result.get(
                                "application_check"
                            )
                        )

                        if application_check:
                            console.print(
                                "\n[bold cyan]"
                                "Application URL discovery:"
                                "[/bold cyan]"
                            )

                            for candidate in (
                                application_check.get(
                                    "candidates",
                                    [],
                                )
                            ):
                                console.print(
                                    f"• {candidate}"
                                )

                            console.print(
                                "\n[bold green]"
                                "✓ Application responded "
                                "successfully"
                                "[/bold green]"
                            )

                            console.print(
                                f"[bold]URL:[/bold] "
                                f"{application_check['url']}"
                            )

                            console.print(
                                f"[bold]HTTP status:[/bold] "
                                f"{application_check['status_code']}"
                            )

                        return

                    last_result = (
                        result["results"][-1]
                    )

    # ---------------------------------------------------------
    # Application health failure
    # ---------------------------------------------------------

    application_check = result.get(
        "application_check"
    )

    if application_check:
        console.print(
            "\n[bold red]"
            "Application health check failed"
            "[/bold red]"
        )

        candidates = application_check.get(
            "candidates",
            [],
        )

        if candidates:
            console.print(
                "\n[bold cyan]"
                "Application URL discovery:"
                "[/bold cyan]"
            )

            for candidate in candidates:
                console.print(
                    f"• {candidate}"
                )

        error = application_check.get("error")

        if error:
            console.print(
                f"\n[bold]Reason:[/bold] "
                f"{error}"
            )

        checked_url = application_check.get(
            "url"
        )

        if checked_url:
            console.print(
                f"[bold]URL:[/bold] "
                f"{checked_url}"
            )

        status_code = application_check.get(
            "status_code"
        )

        if status_code is not None:
            console.print(
                f"[bold]HTTP status:[/bold] "
                f"{status_code}"
            )

    # ---------------------------------------------------------
    # Diagnostic context
    # ---------------------------------------------------------

    diagnostic_context = (
        collect_diagnostic_context(
            path,
            analysis=analysis,
            validation_result=result,
        )
    )

    # TEMPORARY:
    # Keep this only while verifying the context payload.
    print(diagnostic_context)

    diagnosis = diagnose_failure(
        result,
        diagnostic_context,
    )

    # ---------------------------------------------------------
    # Diagnosis output
    # ---------------------------------------------------------

    if diagnosis:
        console.print(
            "\n[bold yellow]"
            "Diagnosis"
            "[/bold yellow]"
        )

        console.print(
            diagnosis["summary"],
            markup=False,
        )

        evidence = diagnosis.get(
            "evidence",
            [],
        )

        if evidence:
            console.print(
                "\n[bold]Evidence:[/bold]"
            )

            for item in evidence:
                console.print(
                    f"• {item}",
                    markup=False,
                )

        likely_causes = diagnosis.get(
            "likely_causes",
            [],
        )

        if likely_causes:
            console.print(
                "\n[bold]Likely causes:[/bold]"
            )

            for item in likely_causes:
                console.print(
                    f"• {item}",
                    markup=False,
                )

        suggested_actions = diagnosis.get(
            "suggested_actions",
            [],
        )

        if suggested_actions:
            console.print(
                "\n[bold]"
                "Suggested actions:"
                "[/bold]"
            )

            for item in suggested_actions:
                console.print(
                    f"• {item}",
                    markup=False,
                )

    # ---------------------------------------------------------
    # Raw command output
    # ---------------------------------------------------------

    if last_result["stderr"]:
        console.print(
            "\n[bold red]"
            "Error:"
            "[/bold red]"
        )

        console.print(
            last_result["stderr"],
            markup=False,
        )

    if last_result["stdout"]:
        console.print(
            "\n[bold]"
            "Output:"
            "[/bold]"
        )

        console.print(
            last_result["stdout"],
            markup=False,
        )

    # ---------------------------------------------------------
    # Container logs
    # ---------------------------------------------------------

    if result["logs"]:
        console.print(
            "\n[bold yellow]"
            "Container logs:"
            "[/bold yellow]"
        )

        console.print(
            result["logs"],
            markup=False,
        )

    raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
