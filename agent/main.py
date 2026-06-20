from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel

from agent.scanner import scan_repo
from agent.detector import detect_stack

from agent.docker_generator import generate_docker_files

app = typer.Typer()
console = Console()


@app.callback()
def main():
    """DevOps Agent CLI."""
    pass


@app.command()
def analyze(path: Annotated[str, typer.Argument(help="Path to the repo")] = ".",):
    """Analyze a repo and detect its stack."""
    repo_info = scan_repo(path)
    analysis = detect_stack(repo_info)

    console.print()
    console.print(Panel.fit("DevOps Agent Analysis", style="bold cyan"))
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
def dockerize(path: Annotated[str, typer.Argument(help="Path to the repo")] = ".",):
    """Generate Docker files for the repo."""
    repo_info = scan_repo(path)
    analysis = detect_stack(repo_info)
    if "Unknown stack" in analysis["detected"]:
        console.print("[bold red]Could not detect a supported app in this folder.[/bold red]")
        console.print("Try running the command inside the actual app directory.")
        raise typer.Exit(code=1)

    created = generate_docker_files(path, analysis)

    console.print()
    console.print(Panel.fit("Dockerize Complete", style="bold cyan"))

    if created:
        console.print("[bold green]Created files:[/bold green]")
        for file in created:
            console.print(f"✓ {file}")
    else:
        console.print("[bold yellow]No files created. Docker files already exist.[/bold yellow]")

if __name__ == "__main__":
    app()