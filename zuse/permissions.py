"""Permission management for tools with side effects."""

from __future__ import annotations

from enum import Enum

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.text import Text


class Decision(Enum):
    ALLOW = "allow"
    DENY = "deny"


def _render_body(text: str) -> Text:
    """Color a preview body: diff lines get red/green/cyan, the rest stays grey."""
    out = Text()
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("@@"):
            style = "#22D3EE"
        elif ln.startswith("+++") or ln.startswith("---"):
            style = "grey50"
        elif ln.startswith("+"):
            style = "#34D399"
        elif ln.startswith("-"):
            style = "#F87171"
        else:
            style = "grey70"
        out.append(ln, style=style)
        if i < len(lines) - 1:
            out.append("\n")
    return out


class PermissionManager:
    """Gates tool execution. Remembers per-tool 'always allow' grants for the
    session, and supports a global yolo (auto-approve) mode."""

    def __init__(self, console: Console, yolo: bool = False) -> None:
        self.console = console
        self.yolo = yolo
        self._always: set[str] = set()

    def reset_session(self) -> None:
        self._always.clear()

    def request(self, tool_name: str, title: str, preview: str) -> Decision:
        if self.yolo or tool_name in self._always:
            return Decision.ALLOW

        body = _render_body(preview.strip() or "(no preview available)")
        self.console.print(
            Panel(
                body,
                title=Text.assemble(("⚠ permission ", "bold #FBBF24"), (title, "#E879F9")),
                title_align="left",
                subtitle=Text("y allow once · n deny · a always allow", style="grey42"),
                subtitle_align="right",
                box=box.ROUNDED,
                border_style="#FBBF24",
                padding=(0, 1),
                expand=False,
            )
        )
        for _ in range(3):
            try:
                raw = self.console.input(
                    "  [bold #FBBF24]allow?[/] [grey50](y/n/a)[/] "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                return Decision.DENY
            choice = raw[:1] if raw else "y"  # empty / Enter = allow once
            if choice == "y":
                return Decision.ALLOW
            if choice == "a":
                self._always.add(tool_name)
                return Decision.ALLOW
            if choice == "n":
                return Decision.DENY
            self.console.print("  [grey50]please answer y, n, or a[/]")
        return Decision.DENY  # too many unrecognized answers — deny to be safe
