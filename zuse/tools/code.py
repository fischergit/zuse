"""Run Python code in a subprocess."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .base import Tool, ToolContext, ToolError, _short


class PythonExec(Tool):
    name = "python"
    description = (
        "Execute a Python 3 snippet in a fresh subprocess and return its output. "
        "Good for calculations, data wrangling, and quick scripts. State does not "
        "persist between calls. Runs in the working directory."
    )
    requires_permission = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python source to execute."},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 60)."},
            },
            "required": ["code"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        code = args["code"]
        timeout = int(args.get("timeout", 60))
        with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, dir=str(ctx.cwd)
        ) as f:
            f.write(code)
            tmp = Path(f.name)
        try:
            proc = subprocess.run(
                [sys.executable, str(tmp)],
                cwd=str(ctx.cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise ToolError(f"Execution timed out after {timeout}s.")
        finally:
            tmp.unlink(missing_ok=True)

        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if len(out) > 30_000:
            out = out[:30_000] + "\n… (truncated)"
        header = f"[exit {proc.returncode}]"
        return f"{header}\n{out}" if out else f"{header} (no output)"

    def permission_preview(self, args: dict[str, Any], ctx: ToolContext) -> str:
        code = args.get("code", "")
        snippet = "\n".join(code.splitlines()[:15])
        return f"Run Python:\n\n{snippet}"

    def call_summary(self, args: dict[str, Any]) -> str:
        first = args.get("code", "").strip().splitlines()
        return _short(first[0] if first else "", 60)
