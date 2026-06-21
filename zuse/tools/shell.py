"""Shell tools: a persistent shell session plus background-process control."""

from __future__ import annotations

from typing import Any

from .base import Tool, ToolContext, ToolError, _short

# Patterns that are obviously destructive — never run.
HARD_BLOCK = ("rm -rf /", ":(){:|:&};:", "mkfs", "dd if=")


def _check_block(command: str) -> None:
    for pat in HARD_BLOCK:
        if pat in command:
            raise ToolError(f"Refusing to run a command containing {pat!r}.")


class Bash(Tool):
    name = "bash"
    description = (
        "Run a shell command in a PERSISTENT shell session: the working directory, "
        "environment variables, and shell state (e.g. an activated virtualenv) carry "
        "over between calls. Use for builds, tests, git, package managers, and "
        "navigation (`cd` sticks). For long-running processes like dev servers, use "
        "run_background instead — a foreground server here will time out."
    )
    requires_permission = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run."},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 120)."},
            },
            "required": ["command"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        command = args["command"]
        _check_block(command)
        if ctx.shell is None:
            raise ToolError("No shell session available.")
        timeout = int(args.get("timeout", 120))
        out, code = ctx.shell.run(command, timeout=timeout)
        out = out.strip()
        if len(out) > 30_000:
            out = out[:30_000] + "\n… (output truncated)"
        header = f"[exit {code}]" if code is not None else "[exit ?]"
        return f"{header}\n{out}" if out else f"{header} (no output)"

    def permission_preview(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return f"$ {args.get('command', '')}"

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("command", ""), 70)


class RunBackground(Tool):
    name = "run_background"
    description = (
        "Start a long-running command as a background process (e.g. a dev server, "
        "file watcher, or build in watch mode). Returns a task id; the process keeps "
        "running and its output is captured. Use bg_logs to read its output, "
        "bg_stop to stop it."
    )
    requires_permission = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        command = args["command"]
        _check_block(command)
        if ctx.background is None:
            raise ToolError("Background manager unavailable.")
        task_id = ctx.background.start(command, str(ctx.cwd))
        return f"Started background task {task_id}: {command}"

    def permission_preview(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return f"$ {args.get('command', '')}  &  (background)"

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("command", ""), 70)


class BgLogs(Tool):
    name = "bg_logs"
    description = "Read recent output (log tail) from a background task started with run_background."
    read_only = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "lines": {"type": "integer", "description": "How many recent lines (default 40)."},
            },
            "required": ["task_id"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        try:
            status = ctx.background.status(args["task_id"])
            logs = ctx.background.logs(args["task_id"], int(args.get("lines", 40)))
        except KeyError:
            raise ToolError(f"No such background task: {args['task_id']}")
        return f"[{status}]\n{logs}"

    def call_summary(self, args: dict[str, Any]) -> str:
        return args.get("task_id", "")


class BgStop(Tool):
    name = "bg_stop"
    description = "Stop a background task started with run_background."
    requires_permission = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"]}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        try:
            return ctx.background.stop(args["task_id"])
        except KeyError:
            raise ToolError(f"No such background task: {args['task_id']}")

    def call_summary(self, args: dict[str, Any]) -> str:
        return args.get("task_id", "")


class BgList(Tool):
    name = "bg_list"
    description = "List background tasks and their status."
    read_only = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        rows = ctx.background.list()
        if not rows:
            return "(no background tasks)"
        return "\n".join(f"{tid}  {state}  {cmd}" for tid, state, cmd in rows)
