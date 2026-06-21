"""Quiet mode: hide the per-tool activity log, show only agent progress."""

from pathlib import Path
from typing import Any

from rich.console import Console

from zuse.agent import Agent
from zuse.config import Config
from zuse.providers.base import ToolCall
from zuse.tools import ToolContext
from zuse.tools.base import Tool


class EchoTool(Tool):
    name = "echo"
    description = "echo"
    read_only = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def run(self, args, ctx) -> str:
        return "echo-output-XYZ"


def _agent(show_actions: bool) -> Agent:
    agent = Agent.__new__(Agent)
    agent.config = Config(show_actions=show_actions)
    agent.console = Console(record=True, force_terminal=False, width=100)
    agent.registry = {"echo": EchoTool()}
    agent.permissions = None
    agent.ctx = ToolContext(
        cwd=Path.cwd(), console=agent.console, permissions=None, config=agent.config
    )
    return agent


def test_quiet_mode_suppresses_the_tool_log():
    agent = _agent(show_actions=False)
    result = agent._execute_tool(ToolCall(id="t1", name="echo", input={}))

    # The tool still ran and returned its output to the model...
    assert result.content == "echo-output-XYZ"
    # ...but nothing was printed to the terminal.
    assert agent.console.export_text().strip() == ""


def test_verbose_mode_shows_the_tool_log():
    agent = _agent(show_actions=True)
    agent._execute_tool(ToolCall(id="t1", name="echo", input={}))

    text = agent.console.export_text()
    assert "echo" in text
    assert "echo-output-XYZ" in text
