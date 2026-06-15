"""Expose tools from connected MCP servers as Zuse tools.

Each MCP tool becomes a Zuse tool named `mcp__<server>__<tool>`, mirroring the
common namespacing convention so names never collide across servers.
"""

from __future__ import annotations

from typing import Any

from .base import Tool, ToolContext, ToolError, ToolOutput, _short


class MCPTool(Tool):
    requires_permission = True  # external servers can have side effects

    def __init__(self, server, tool_def: dict) -> None:
        self._server = server
        self._tool_name = tool_def["name"]
        self.name = f"mcp__{server.name}__{tool_def['name']}"
        desc = (tool_def.get("description") or "").strip()
        self.description = f"[MCP:{server.name}] {desc}" if desc else f"[MCP:{server.name}] {self._tool_name}"
        self._schema = tool_def.get("inputSchema") or {"type": "object", "properties": {}}

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._schema

    def run(self, args: dict[str, Any], ctx: ToolContext):
        try:
            text, images, is_error = self._server.call_tool(self._tool_name, args or {})
        except Exception as e:  # noqa: BLE001
            raise ToolError(f"MCP call failed: {e}")
        if is_error:
            raise ToolError(text)
        return ToolOutput(text=text, images=images) if images else text

    def permission_preview(self, args: dict[str, Any], ctx: ToolContext) -> str:
        argstr = ", ".join(f"{k}={_short(v, 40)}" for k, v in (args or {}).items())
        return f"MCP {self._server.name} · {self._tool_name}({argstr})"

    def call_summary(self, args: dict[str, Any]) -> str:
        return ", ".join(f"{k}={_short(v, 30)}" for k, v in (args or {}).items())


def mcp_tools(manager) -> list[Tool]:
    tools: list[Tool] = []
    for server in manager.servers:
        for tool_def in server.tools:
            try:
                tools.append(MCPTool(server, tool_def))
            except (KeyError, TypeError):
                continue
    return tools
