"""Minimal Model Context Protocol (MCP) client.

Connects to MCP servers over stdio (JSON-RPC 2.0, newline-delimited) and exposes
their tools to Zuse. Dependency-light and synchronous, matching the rest of the
codebase — no async SDK required.

Servers are configured in ~/.zuse/mcp.json, mirroring the common format:

    {
      "mcpServers": {
        "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/nik"]},
        "fetch":      {"command": "uvx", "args": ["mcp-server-fetch"]}
      }
    }
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from typing import Any

from .config import CONFIG_DIR

MCP_CONFIG = CONFIG_DIR / "mcp.json"
_PROTOCOL_VERSION = "2024-11-05"


class MCPError(Exception):
    pass


class MCPServer:
    """One MCP server subprocess driven by synchronous JSON-RPC over stdio."""

    def __init__(self, name: str, command: str, args: list[str], env: dict | None = None):
        self.name = name
        self.command = command
        self.args = args
        self.env = env or {}
        self.proc: subprocess.Popen | None = None
        self.tools: list[dict] = []
        self._id = 0
        self._lock = threading.Lock()

    def start(self, timeout: int = 30) -> None:
        full_env = {**os.environ, **self.env}
        self.proc = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=full_env,
        )
        self._request("initialize", {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "zuse", "version": "0.1.0"},
        }, timeout=timeout)
        self._notify("notifications/initialized")
        self.tools = self._request("tools/list").get("tools", [])

    def _send(self, msg: dict) -> None:
        if not self.proc or not self.proc.stdin:
            raise MCPError("server not running")
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _notify(self, method: str, params: dict | None = None) -> None:
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._send(msg)

    def _request(self, method: str, params: dict | None = None, timeout: int = 60) -> dict:
        with self._lock:
            if self.proc is None or self.proc.poll() is not None:
                raise MCPError(f"MCP server '{self.name}' is not running")
            self._id += 1
            req_id = self._id
            msg: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
            if params is not None:
                msg["params"] = params
            self._send(msg)

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                line = self.proc.stdout.readline()  # type: ignore[union-attr]
                if not line:
                    raise MCPError(f"MCP server '{self.name}' closed the connection")
                line = line.strip()
                if not line:
                    continue
                try:
                    resp = json.loads(line)
                except json.JSONDecodeError:
                    continue  # skip non-JSON noise
                if resp.get("id") == req_id:
                    if "error" in resp:
                        raise MCPError(resp["error"].get("message", str(resp["error"])))
                    return resp.get("result", {})
                # otherwise it's a notification or another id — ignore
            raise MCPError(f"MCP server '{self.name}' timed out on {method}")

    def call_tool(self, tool_name: str, arguments: dict) -> tuple[str, list[str], bool]:
        """Call a tool. Returns (text, images_base64, is_error)."""
        result = self._request("tools/call", {"name": tool_name, "arguments": arguments})
        is_error = bool(result.get("isError"))
        texts: list[str] = []
        images: list[str] = []
        for block in result.get("content", []):
            btype = block.get("type")
            if btype == "text":
                texts.append(block.get("text", ""))
            elif btype == "image" and block.get("data"):
                images.append(block["data"])
            elif btype == "resource":
                res = block.get("resource", {})
                texts.append(res.get("text") or f"[resource: {res.get('uri', '')}]")
        return ("\n".join(texts).strip() or "(no output)"), images, is_error

    def close(self) -> None:
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                try:
                    self.proc.kill()
                except Exception:  # noqa: BLE001
                    pass


class MCPManager:
    """Loads the MCP config, starts servers, and holds the connections."""

    def __init__(self) -> None:
        self.servers: list[MCPServer] = []
        self.errors: list[tuple[str, str]] = []

    @staticmethod
    def configured() -> bool:
        return MCP_CONFIG.exists()

    def connect_all(self) -> None:
        if not MCP_CONFIG.exists():
            return
        try:
            cfg = json.loads(MCP_CONFIG.read_text())
        except (json.JSONDecodeError, OSError) as e:
            self.errors.append(("<config>", f"could not read mcp.json: {e}"))
            return
        servers = cfg.get("mcpServers", cfg.get("servers", {}))
        for name, spec in servers.items():
            if spec.get("disabled"):
                continue
            command = spec.get("command")
            if not command:
                self.errors.append((name, "missing 'command'"))
                continue
            srv = MCPServer(name, command, spec.get("args", []), spec.get("env"))
            try:
                srv.start()
                self.servers.append(srv)
            except Exception as e:  # noqa: BLE001
                self.errors.append((name, str(e)))
                srv.close()

    def shutdown(self) -> None:
        for s in self.servers:
            s.close()
        self.servers = []
