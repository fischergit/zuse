"""Tool registry."""

from __future__ import annotations

import sys

from .base import Tool, ToolContext, ToolError, ToolOutput, TodoItem
from .code import PythonExec
from .filesystem import EditFile, Glob, Grep, ListDirectory, ReadFile, WriteFile
from .productivity import Remember, TodoWrite
from .shell import Bash, BgList, BgLogs, BgStop, RunBackground
from .subagent import Crew, Task


def default_tools() -> list[Tool]:
    """The full client-side tool set, in a stable order (matters for prompt
    caching — the tool list renders at position 0 of the cached prefix)."""
    tools: list[Tool] = [
        ReadFile(),
        WriteFile(),
        EditFile(),
        ListDirectory(),
        Glob(),
        Grep(),
        Bash(),
        RunBackground(),
        BgLogs(),
        BgStop(),
        BgList(),
        PythonExec(),
        TodoWrite(),
        Remember(),
        Task(),
        Crew(),
    ]
    if sys.platform == "darwin":
        from .computer import computer_tools
        from .mac import mac_tools

        tools.extend(mac_tools())
        tools.extend(computer_tools())

    from .browser import available as browser_available
    from .browser import browser_tools

    if browser_available():
        tools.extend(browser_tools())
    return tools


def build_registry(tools: list[Tool]) -> dict[str, Tool]:
    return {t.name: t for t in tools}


__all__ = [
    "Tool",
    "ToolContext",
    "ToolError",
    "ToolOutput",
    "TodoItem",
    "default_tools",
    "build_registry",
]
