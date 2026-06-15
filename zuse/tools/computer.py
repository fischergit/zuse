"""Computer-use tools for macOS: see the screen (vision) and control the
mouse/keyboard at pixel coordinates. Mouse/keyboard use Quartz (pyobjc);
screen capture uses the built-in screencapture + sips.

Coordinates are in the screen's *logical* points (the same space the screenshot
is scaled to), so what the model sees maps 1:1 to where it clicks.
"""

from __future__ import annotations

import base64
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .base import Tool, ToolContext, ToolError, ToolOutput, _short

# macOS virtual key codes for named keys.
_KEYCODES = {
    "return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51,
    "backspace": 51, "escape": 53, "esc": 53, "left": 123, "right": 124,
    "down": 125, "up": 126, "home": 115, "end": 119, "pageup": 116,
    "pagedown": 121, "forwarddelete": 117,
}
_KEYCODES.update({f"f{i}": kc for i, kc in zip(range(1, 13),
                  [122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111])})

_MODFLAGS = {"cmd": 1 << 20, "command": 1 << 20, "shift": 1 << 17,
             "alt": 1 << 19, "option": 1 << 19, "opt": 1 << 19,
             "ctrl": 1 << 18, "control": 1 << 18, "fn": 1 << 23}


def _logical_size() -> tuple[int, int]:
    from AppKit import NSScreen

    f = NSScreen.mainScreen().frame()
    return int(f.size.width), int(f.size.height)


def _capture_logical() -> tuple[str, int, int]:
    """Capture the full screen, downscale to logical points, return (b64, w, h)."""
    w, h = _logical_size()
    tmp = Path(tempfile.mktemp(suffix=".png"))
    try:
        cap = subprocess.run(["screencapture", "-x", "-t", "png", str(tmp)],
                             capture_output=True, timeout=20)
        if cap.returncode != 0 or not tmp.exists():
            raise ToolError((cap.stderr or b"screencapture failed").decode(errors="replace"))
        # Downscale retina pixels → logical width so coords match clicks.
        subprocess.run(["sips", "--resampleWidth", str(w), str(tmp)],
                       capture_output=True, timeout=20)
        data = tmp.read_bytes()
    finally:
        tmp.unlink(missing_ok=True)
    return base64.standard_b64encode(data).decode(), w, h


class Screen(Tool):
    name = "screen"
    description = (
        "Take a screenshot of the Mac's screen and SEE it (returns the image to "
        "you). Use this to look at what's currently on screen before deciding where "
        "to click or type. The image is in logical screen coordinates — the same "
        "x,y space the mouse_click/mouse_move tools expect. Requires a "
        "vision-capable model."
    )
    read_only = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolOutput:
        try:
            b64, w, h = _capture_logical()
        except ToolError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ToolError(f"Screen capture failed: {e}")
        return ToolOutput(text=f"Screenshot captured. Screen is {w}x{h} (logical points).",
                          images=[b64])


def _quartz():
    try:
        import Quartz  # noqa: PLC0415

        return Quartz
    except ImportError:
        raise ToolError(
            "Mouse/keyboard control needs pyobjc-Quartz. Install it with: "
            "pip install pyobjc-framework-Quartz"
        )


def _post_mouse(x: float, y: float, button: str, count: int) -> None:
    Q = _quartz()
    btn = {"left": Q.kCGMouseButtonLeft, "right": Q.kCGMouseButtonRight,
           "center": Q.kCGMouseButtonCenter}.get(button, Q.kCGMouseButtonLeft)
    down = {"left": Q.kCGEventLeftMouseDown, "right": Q.kCGEventRightMouseDown,
            "center": Q.kCGEventOtherMouseDown}.get(button, Q.kCGEventLeftMouseDown)
    up = {"left": Q.kCGEventLeftMouseUp, "right": Q.kCGEventRightMouseUp,
          "center": Q.kCGEventOtherMouseUp}.get(button, Q.kCGEventLeftMouseUp)
    pos = (x, y)
    move = Q.CGEventCreateMouseEvent(None, Q.kCGEventMouseMoved, pos, btn)
    Q.CGEventPost(Q.kCGHIDEventTap, move)
    time.sleep(0.02)
    for i in range(count):
        d = Q.CGEventCreateMouseEvent(None, down, pos, btn)
        Q.CGEventSetIntegerValueField(d, Q.kCGMouseEventClickState, i + 1)
        Q.CGEventPost(Q.kCGHIDEventTap, d)
        u = Q.CGEventCreateMouseEvent(None, up, pos, btn)
        Q.CGEventSetIntegerValueField(u, Q.kCGMouseEventClickState, i + 1)
        Q.CGEventPost(Q.kCGHIDEventTap, u)
        time.sleep(0.03)


class MouseClick(Tool):
    name = "mouse_click"
    description = (
        "Click the mouse at logical screen coordinates (x, y). Take a `screen` "
        "shot first to decide where. button: left|right|center; count: 1 (single) "
        "or 2 (double-click)."
    )
    requires_permission = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "x": {"type": "integer"}, "y": {"type": "integer"},
                "button": {"type": "string", "enum": ["left", "right", "center"]},
                "count": {"type": "integer", "description": "1 or 2 (double-click)."},
            },
            "required": ["x", "y"],
        }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        x, y = int(args["x"]), int(args["y"])
        button = args.get("button", "left")
        count = int(args.get("count", 1))
        _post_mouse(x, y, button, count)
        return f"{'Double-' if count == 2 else ''}{button}-clicked at ({x}, {y})."

    def permission_preview(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return f"{args.get('button', 'left')}-click at ({args.get('x')}, {args.get('y')})"

    def call_summary(self, args: dict[str, Any]) -> str:
        return f"({args.get('x')}, {args.get('y')})"


class MouseMove(Tool):
    name = "mouse_move"
    description = "Move the mouse cursor to logical screen coordinates (x, y) without clicking."
    requires_permission = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object",
                "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
                "required": ["x", "y"]}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        Q = _quartz()
        x, y = int(args["x"]), int(args["y"])
        ev = Q.CGEventCreateMouseEvent(None, Q.kCGEventMouseMoved, (x, y), Q.kCGMouseButtonLeft)
        Q.CGEventPost(Q.kCGHIDEventTap, ev)
        return f"Moved cursor to ({x}, {y})."

    def call_summary(self, args: dict[str, Any]) -> str:
        return f"({args.get('x')}, {args.get('y')})"


class TypeText(Tool):
    name = "type_text"
    description = (
        "Type a string of text at the current keyboard focus (types unicode "
        "directly, so it works regardless of keyboard layout). Click where you want "
        "to type first."
    )
    requires_permission = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        Q = _quartz()
        text = args["text"]
        for ch in text:
            for is_down in (True, False):
                ev = Q.CGEventCreateKeyboardEvent(None, 0, is_down)
                Q.CGEventKeyboardSetUnicodeString(ev, len(ch), ch)
                Q.CGEventPost(Q.kCGHIDEventTap, ev)
            time.sleep(0.004)
        return f"Typed {len(text)} characters."

    def permission_preview(self, args: dict[str, Any], ctx: ToolContext) -> str:
        return f"Type: {args.get('text', '')[:200]}"

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("text", ""))


class KeyPress(Tool):
    name = "key_press"
    description = (
        "Press a key or key combination, e.g. 'return', 'escape', 'cmd+s', "
        "'cmd+shift+4', 'cmd+tab', 'down'. Use for shortcuts and navigation."
    )
    requires_permission = True

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"keys": {"type": "string"}}, "required": ["keys"]}

    def run(self, args: dict[str, Any], ctx: ToolContext) -> str:
        Q = _quartz()
        parts = [p.strip().lower() for p in args["keys"].replace(" ", "").split("+") if p.strip()]
        if not parts:
            raise ToolError("No keys given.")
        *mods, key = parts
        flags = 0
        for m in mods:
            if m not in _MODFLAGS:
                raise ToolError(f"Unknown modifier: {m}")
            flags |= _MODFLAGS[m]
        if key in _KEYCODES:
            code = _KEYCODES[key]
        elif len(key) == 1:
            code = _char_keycode(key)
            if code is None:
                raise ToolError(f"Cannot map key: {key}")
        else:
            raise ToolError(f"Unknown key: {key}")
        for is_down in (True, False):
            ev = Q.CGEventCreateKeyboardEvent(None, code, is_down)
            if flags:
                Q.CGEventSetFlags(ev, flags)
            Q.CGEventPost(Q.kCGHIDEventTap, ev)
            time.sleep(0.01)
        return f"Pressed {args['keys']}."

    def call_summary(self, args: dict[str, Any]) -> str:
        return _short(args.get("keys", ""))


# Minimal US-layout keycode map for single characters used in shortcuts.
_CHAR_KEYS = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8,
    "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26,
    "8": 28, "0": 29, "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38,
    "k": 40, "n": 45, "m": 46, ".": 47, ",": 43, "/": 44, ";": 41, "'": 39,
    "-": 27, "=": 24, "`": 50,
}


def _char_keycode(ch: str):
    return _CHAR_KEYS.get(ch.lower())


def computer_tools() -> list[Tool]:
    return [Screen(), MouseClick(), MouseMove(), TypeText(), KeyPress()]
