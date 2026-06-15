"""Planning and memory tools: todo list and persistent remember."""

from __future__ import annotations

from typing import Any

from .base import Tool, ToolContext, ToolError, TodoItem, _short

_STATUS = {"pending", "in_progress", "done"}


class TodoWrite(Tool):
    name = "todo_write"
    description = (
        "Create or update the task list for the current work. Pass the full list "
        "of items each time with their statuses ('pending', 'in_progress', 'done'). "
        "Keep exactly one item 'in_progress'. Use this to plan multi-step tasks and "
        "show the user your progress."
    )
    read_only = True  # no filesystem side effects; safe to run without prompting

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "status": {"type": "string", "enum": sorted(_STATUS)},
                        },
                        "required": ["text", "status"],
                    },
                }
            },
            "required": ["items"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        items = args["items"]
        new_todos: list[TodoItem] = []
        for it in items:
            status = it.get("status", "pending")
            if status not in _STATUS:
                raise ToolError(f"Invalid status {status!r}.")
            new_todos.append(TodoItem(text=it["text"], status=status))
        ctx.todos[:] = new_todos
        # Render so the user sees the plan immediately.
        from ..ui import render_todos

        render_todos(ctx.console, ctx.todos)
        done = sum(1 for t in new_todos if t.status == "done")
        return f"Task list updated ({done}/{len(new_todos)} done)."

    def call_summary(self, args: dict[str, Any]) -> str:
        return f"{len(args.get('items', []))} items"


class Remember(Tool):
    name = "remember"
    description = (
        "Save something durable to persistent memory that survives across sessions, "
        "so you get better over time. Use 'preference' for how the user likes things, "
        "'fact' for stable truths about their machine/projects, and 'procedure' for a "
        "reusable how-to you worked out. Only store things genuinely worth recalling "
        "later — not transient details."
    )
    read_only = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The thing to remember (one sentence)."},
                "kind": {
                    "type": "string",
                    "enum": ["preference", "fact", "procedure"],
                    "description": "What kind of knowledge this is.",
                },
            },
            "required": ["text"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        if ctx.knowledge is None:
            raise ToolError("Knowledge store unavailable.")
        kind = args.get("kind", "fact")
        entry = ctx.knowledge.add(kind, args["text"])
        if entry is None:
            return "Already known — nothing new saved."
        return f"Learned ({kind}): {entry.text}"

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("text", ""))
