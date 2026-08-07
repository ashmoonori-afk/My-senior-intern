# Copyright (c) 2026 My Senior Intern contributors

"""CLI and initial TUI contract tests."""

import pytest
from textual.widgets import Static
from typer.testing import CliRunner

from senior_intern.cli import app
from senior_intern.tui.app import SeniorInternApp

runner = CliRunner()


def test_cli_help_lists_required_entry_surfaces() -> None:
    """The command help exposes the user and scheduled-worker entry surfaces."""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    assert "tui" in result.output
    assert "run" in result.output
    assert "doctor" in result.output


@pytest.mark.anyio
async def test_tui_onboarding_nontechnical_red() -> None:
    """Launching the TUI shows the first plain-language onboarding decision."""
    app_under_test = SeniorInternApp()

    async with app_under_test.run_test(size=(100, 30)):
        title = app_under_test.query_one("#welcome-title", Static)

    assert "안녕하세요" in str(title.render())
