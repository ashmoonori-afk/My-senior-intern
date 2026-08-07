# Copyright (c) 2026 My Senior Intern contributors

"""Command-line entry point for My Senior Intern."""

import platform
import sys
from typing import Annotated

import typer

from senior_intern.tui.app import run_tui

app = typer.Typer(
    add_completion=False,
    help="Safe local document automation for Windows and macOS.",
    pretty_exceptions_enable=False,
)


@app.callback(invoke_without_command=True)
def root(context: typer.Context) -> None:
    """Open the guided TUI when no internal command is selected."""
    if context.invoked_subcommand is None:
        run_tui()


@app.command()
def tui() -> None:
    """Open the guided My Senior Intern interface."""
    run_tui()


@app.command("run")
def run_worker(
    *,
    scheduled: Annotated[
        bool,
        typer.Option("--scheduled", help="Run as an operating-system scheduled task."),
    ] = False,
) -> None:
    """Run one safe headless worker cycle."""
    mode = "scheduled" if scheduled else "manual"
    typer.echo(f"No folders are configured; {mode} run changed 0 files.")


@app.command()
def doctor() -> None:
    """Show a non-sensitive local compatibility summary."""
    typer.echo("My Senior Intern environment")
    typer.echo(f"Operating system: {platform.system()}")
    typer.echo(f"Python: {sys.version_info.major}.{sys.version_info.minor}")
    typer.echo("Status: ready for guided setup")


def main() -> None:
    """Run the My Senior Intern command-line application."""
    app()


if __name__ == "__main__":
    main()
