"""macOS control tools: AppleScript, app launching, clipboard, screenshots,
notifications, and system info. Registered only on Darwin."""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import CONFIG_DIR
from .base import Tool, ToolContext, ToolError, _short


def _run(cmd: list[str], inp: str | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=inp, capture_output=True, text=True, timeout=timeout)


class AppleScript(Tool):
    name = "applescript"
    description = (
        "Run an AppleScript via osascript to control macOS and its apps — Finder, "
        "Safari, Mail, Notes, Music, Calendar, Reminders, System Events (keystrokes, "
        "menu clicks, window control), and more. This is the most powerful way to "
        "automate the Mac. Return value is the script's result."
    )
    requires_permission = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "The AppleScript source to run."},
            },
            "required": ["script"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        try:
            proc = _run(["osascript", "-"], inp=args["script"], timeout=120)
        except subprocess.TimeoutExpired:
            raise ToolError("AppleScript timed out.")
        except FileNotFoundError:
            raise ToolError("osascript not found (not on macOS?).")
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode != 0:
            raise ToolError(err or "AppleScript failed.")
        return out or "(ok)"

    def permission_preview(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return "Run AppleScript:\n\n" + "\n".join(args.get("script", "").splitlines()[:15])

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("script", "").strip().splitlines()[0] if args.get("script") else "", 60)


class OpenMac(Tool):
    name = "open"
    description = (
        "Open a file, folder, URL, or application using the macOS `open` command. "
        "Examples: open a website in the browser, reveal a folder in Finder, or "
        "launch an app by name."
    )
    requires_permission = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Path, URL, or (with app) a document."},
                "app": {"type": "string", "description": "Optional application name to open with."},
            },
            "required": ["target"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        cmd = ["open"]
        if app := args.get("app"):
            cmd += ["-a", app]
        cmd.append(args["target"])
        try:
            proc = _run(cmd, timeout=30)
        except FileNotFoundError:
            raise ToolError("`open` not found (not on macOS?).")
        if proc.returncode != 0:
            raise ToolError((proc.stderr or "open failed").strip())
        return f"Opened {args['target']}" + (f" with {args['app']}" if args.get("app") else "")

    def permission_preview(self, args: dict[str, Any], ctx: ToolContext) -> str:
        tgt = args.get("target", "")
        return f"open {('-a ' + args['app'] + ' ') if args.get('app') else ''}{tgt}"

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("target", ""))


class Notify(Tool):
    name = "notify"
    description = "Show a macOS notification banner with a title and message."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["message"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        title = (args.get("title") or "Zuse").replace('"', "'")
        msg = args["message"].replace('"', "'")
        script = f'display notification "{msg}" with title "{title}"'
        _run(["osascript", "-e", script], timeout=15)
        return "Notification shown."

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("message", ""))


class ClipboardRead(Tool):
    name = "clipboard_read"
    description = "Read the current contents of the macOS clipboard."
    read_only = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        try:
            proc = _run(["pbpaste"], timeout=10)
        except FileNotFoundError:
            raise ToolError("pbpaste not found (not on macOS?).")
        text = proc.stdout
        return text if text.strip() else "(clipboard is empty)"


class ClipboardWrite(Tool):
    name = "clipboard_write"
    description = "Copy the given text to the macOS clipboard."
    requires_permission = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        try:
            _run(["pbcopy"], inp=args["text"], timeout=10)
        except FileNotFoundError:
            raise ToolError("pbcopy not found (not on macOS?).")
        return f"Copied {len(args['text'])} characters to clipboard."

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("text", ""))


class Screenshot(Tool):
    name = "screenshot"
    description = (
        "Capture the screen to a PNG file and return its path. Captures the full "
        "screen by default. (macOS may prompt for Screen Recording permission on "
        "first use.)"
    )
    requires_permission = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Output PNG path (optional)."},
            },
            "required": [],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        if args.get("path"):
            out = ctx.resolve(args["path"])
        else:
            shots = CONFIG_DIR / "screenshots"
            shots.mkdir(parents=True, exist_ok=True)
            out = shots / f"shot-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        try:
            proc = _run(["screencapture", "-x", str(out)], timeout=30)
        except FileNotFoundError:
            raise ToolError("screencapture not found (not on macOS?).")
        if proc.returncode != 0 or not Path(out).exists():
            raise ToolError((proc.stderr or "screenshot failed").strip())
        return f"Saved screenshot to {out}"

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("path", "full screen"))


class SystemInfo(Tool):
    name = "system_info"
    description = "Report basic macOS system information (version, host, hardware, disk, uptime)."
    read_only = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        parts = []
        for label, cmd in [
            ("macOS", ["sw_vers", "-productVersion"]),
            ("Host", ["hostname"]),
            ("Arch", ["uname", "-m"]),
            ("Uptime", ["uptime"]),
        ]:
            try:
                r = _run(cmd, timeout=10)
                parts.append(f"{label}: {r.stdout.strip()}")
            except Exception:  # noqa: BLE001
                pass
        try:
            df = _run(["df", "-h", "/"], timeout=10).stdout.strip().splitlines()
            if len(df) >= 2:
                parts.append("Disk /: " + " ".join(df[1].split()[1:5]))
        except Exception:  # noqa: BLE001
            pass
        return "\n".join(parts) if parts else "(no info)"


def mac_tools() -> list[Tool]:
    return [
        AppleScript(),
        OpenMac(),
        Notify(),
        ClipboardRead(),
        ClipboardWrite(),
        Screenshot(),
        SystemInfo(),
    ]
