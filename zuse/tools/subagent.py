"""Sub-agent tool: delegate an isolated sub-task to a nested agent loop."""

from __future__ import annotations

from typing import Any

from .base import Tool, ToolContext, ToolError, _short


class Task(Tool):
    name = "task"
    description = (
        "Delegate a focused, self-contained sub-task to a sub-agent that runs its "
        "own tool loop and returns a final report. Use for parallelizable or "
        "independent work (e.g. 'research how X is implemented across the codebase' "
        "or 'summarize these files'). The sub-agent does not share your conversation "
        "— give it complete, standalone instructions."
    )
    read_only = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "instructions": {
                    "type": "string",
                    "description": "Complete, standalone task description for the sub-agent.",
                },
                "max_steps": {
                    "type": "integer",
                    "description": "Maximum tool-loop iterations for the sub-agent (default 12).",
                },
            },
            "required": ["instructions"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        if ctx.spawn_subagent is None:
            raise ToolError("Sub-agents are not available in this context.")
        max_steps = int(args.get("max_steps", 12))
        return ctx.spawn_subagent(args["instructions"], max_steps)

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("instructions", ""), 70)
