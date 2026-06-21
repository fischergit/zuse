"""Tool abstraction: schema, permissions, and execution context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from rich.console import Console

    from ..config import Config
    from ..permissions import PermissionManager


@dataclass
class TodoItem:
    text: str
    status: str = "pending"  # pending | in_progress | done


@dataclass
class ToolContext:
    """Shared state passed to every tool invocation."""

    cwd: Path
    console: "Console"
    permissions: "PermissionManager"
    config: "Config"
    todos: list[TodoItem] = field(default_factory=list)
    knowledge: Any = None    # KnowledgeStore, for the `remember` tool
    shell: Any = None        # ShellSession, for the persistent `bash` tool
    background: Any = None    # BackgroundManager, for run_background et al.
    journal: Any = None      # EditJournal, for /undo of file changes
    browser: Any = None      # BrowserManager, for the browser_* tools
    # Factory to spawn a sub-agent (set by the Agent at runtime). Signature:
    # (task: str, max_steps: int) -> str
    spawn_subagent: Callable[[str, int], str] | None = None
    # Factory to run a small multi-agent crew. Signature:
    # (goal: str, tasks: list[dict], mode: str, max_steps: int) -> str
    spawn_crew: Callable[[str, list[dict[str, Any]], str, int], str] | None = None

    def resolve(self, path: str) -> Path:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self.cwd / p
        return p


class ToolError(Exception):
    """Raised by a tool to signal a recoverable error reported back to Claude."""


@dataclass
class ToolOutput:
    """A tool may return this instead of a plain string to attach images
    (base64 PNG) that vision-capable models can see — e.g. the `screen` tool."""

    text: str
    images: list[str] = field(default_factory=list)


class Tool(ABC):
    name: str = ""
    description: str = ""
    requires_permission: bool = False
    read_only: bool = False

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]: ...

    @abstractmethod
    def run(self, args: dict[str, Any], ctx: ToolContext) -> str: ...

    def to_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def permission_preview(self, args: dict[str, Any], ctx: ToolContext) -> str:
        """Human-readable summary shown in the permission prompt."""
        return ", ".join(f"{k}={v!r}" for k, v in args.items())

    def call_summary(self, args: dict[str, Any]) -> str:
        """One-line summary shown in the tool-call panel."""
        return ", ".join(f"{k}={_short(v)}" for k, v in args.items())


def _short(value: Any, limit: int = 60) -> str:
    s = str(value).replace("\n", " ⏎ ")
    return s if len(s) <= limit else s[:limit] + "…"
