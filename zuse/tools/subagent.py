"""Sub-agent tools: delegate work to nested agent loops and specialist crews."""

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


class Crew(Tool):
    name = "crew"
    description = (
        "Run a coordinated mini-team of specialist sub-agents for a larger task. "
        "Use this when work can be split between roles such as planner, researcher, "
        "coder, tester, and reviewer. Provide a clear goal and either explicit tasks "
        "or leave tasks empty for the orchestrator to use a default plan. The crew "
        "returns a combined report with findings, actions, verification, and next steps."
    )
    read_only = False

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "Overall objective for the multi-agent crew.",
                },
                "tasks": {
                    "type": "array",
                    "description": (
                        "Optional ordered tasks. Each item may contain role, title, "
                        "instructions, and max_steps."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string"},
                            "title": {"type": "string"},
                            "instructions": {"type": "string"},
                            "max_steps": {"type": "integer"},
                        },
                    },
                },
                "mode": {
                    "type": "string",
                    "enum": ["auto", "research", "implementation", "review"],
                    "description": "Crew profile to use when tasks are omitted (default auto).",
                },
                "max_steps_per_agent": {
                    "type": "integer",
                    "description": "Default maximum tool-loop iterations per specialist (default 10).",
                },
            },
            "required": ["goal"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        if ctx.spawn_crew is None:
            raise ToolError("Multi-agent crews are not available in this context.")
        goal = str(args.get("goal", "")).strip()
        if not goal:
            raise ToolError("crew requires a non-empty goal.")
        raw_tasks = args.get("tasks") or []
        tasks = raw_tasks if isinstance(raw_tasks, list) else []
        mode = str(args.get("mode") or "auto")
        max_steps = int(args.get("max_steps_per_agent", 10))
        return ctx.spawn_crew(goal, tasks, mode, max_steps)

    def call_summary(self, args: dict[str, Any]) -> str:
        tasks = args.get("tasks") or []
        count = len(tasks) if isinstance(tasks, list) else 0
        return f"{_short(args.get('goal', ''), 58)} · {count or 'auto'} task(s)"
