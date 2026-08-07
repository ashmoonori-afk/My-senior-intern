# Copyright (c) 2026 My Senior Intern contributors

"""Textual application shell."""

from typing import ClassVar, override

from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.widgets import Footer, Static


class SeniorInternApp(App[None]):
    """Nontechnical-user interface for My Senior Intern."""

    CSS: ClassVar[str] = """
    Screen {
        align: center middle;
    }

    #welcome-card {
        width: 72;
        max-width: 90%;
        height: auto;
        border: round $success;
        padding: 1 3;
    }

    #welcome-progress {
        color: $text-muted;
        margin-bottom: 1;
    }

    #welcome-title {
        text-style: bold;
        color: $success;
        margin-bottom: 1;
    }

    #welcome-copy {
        margin-bottom: 1;
    }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        ("q", "quit", "종료"),
        ("escape", "quit", "뒤로"),
    ]

    @override
    def compose(self) -> ComposeResult:
        """Compose the initial application shell."""
        yield Static("My Senior Intern · 안전한 문서 업무 도우미", id="app-header")
        with Vertical(id="welcome-card"):
            yield Static("1/10 · 시작", id="welcome-progress")
            yield Static(
                "안녕하세요. My Senior Intern이 문서 정리를 도와드릴게요.",
                id="welcome-title",
            )
            yield Static(
                "사용자가 쉬는 동안 문서를 안전하게 정리하고 필요한 초안을 준비합니다.",
                id="welcome-copy",
            )
            yield Static("1  시작하기    2  먼저 어떤 일을 하는지 보기    3  종료")
            yield Static("방향키 또는 숫자키로 고르고 Enter를 눌러주세요.")
        yield Footer()


def run_tui() -> None:
    """Run the interactive Textual application."""
    SeniorInternApp().run()
