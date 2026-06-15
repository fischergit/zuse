"""Terminal rendering: gradient banner, streaming view, tool log, todos."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

if TYPE_CHECKING:
    from .tools.base import TodoItem

# --- palette (truecolor) --------------------------------------------------
CYAN = "#22D3EE"
SKY = "#38BDF8"
INDIGO = "#6366F1"
VIOLET = "#8B5CF6"
PINK = "#E879F9"
GREEN = "#34D399"
AMBER = "#FBBF24"
RED = "#F87171"
GREY = "#6B7280"
FAINT = "grey37"

ACCENT = CYAN
ASSISTANT_STYLE = "white"
THINKING_STYLE = "grey50"
BANNER_STYLE = "bold white"

# Wide slanted logo (rebuilt from the brand mark) — used on wide terminals.
BANNER_WIDE = """
   +&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&
  &&&&&
&&$  &&&&&&&&&&&&&&&   &&&          &&&   &&&&&&&&&&&&&&&   &&&&&&&&&&&&&&&
&&x            &$&$&&  &&&          &&$  &&&               x&&
&&;           &&&&&&   &&&          &&&  &&&               &&&
&&+      &&&&&&&       &&$          &&$   &&&&&&&&&&&&&&&  &&&&&&&&&&&&&&&&
&&;  +&&&&             &&$          &&&                x&  $&x
&&&  $&&&&&&&&&&&&&&&   &&&&&&&&&&&&&&   &&&&&&&&&&&&&&&&  &&&&&&&&&&&&&&&&
 &&&
   &&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&
"""

# Compact block logo — fallback on narrow terminals.
BANNER = r"""
           ▄▄   ▄▄    ▄▄▄▄
 ███████╗ ██╗   ██╗ ███████╗ ███████╗
 ╚══███╔╝ ██║   ██║ ██╔════╝ ██╔════╝
   ███╔╝  ██║   ██║ ███████╗ █████╗
  ███╔╝   ██║   ██║ ╚════██║ ██╔══╝
 ███████╗ ╚██████╔╝ ███████║ ███████╗
 ╚══════╝  ╚═════╝  ╚══════╝ ╚══════╝
"""

TOOL_ICONS = {
    "read_file": "📖", "write_file": "✍ ", "edit_file": "✏ ", "list_directory": "📂",
    "glob": "🔎", "grep": "🔍", "bash": "❯", "python": "🐍", "todo_write": "◷",
    "remember": "🧠", "task": "🤖", "applescript": "🍎", "open": "↗",
    "clipboard_read": "📋", "clipboard_write": "📋", "screenshot": "📸",
    "notify": "🔔", "system_info": "💻", "web_search": "🌐", "web_fetch": "🌐",
    "screen": "👁", "mouse_click": "🖱", "mouse_move": "🖱", "type_text": "⌨",
    "key_press": "⌨", "run_background": "🚀", "bg_logs": "📜", "bg_stop": "■",
    "bg_list": "≡", "browser_open": "🌐", "browser_read": "📄", "browser_links": "🔗",
    "browser_click": "🖱", "browser_type": "⌨", "browser_screenshot": "📸",
}


def make_console() -> Console:
    return Console()


def _banner_text(lines: list[str]) -> Text:
    art = Text()
    for line in lines:
        art.append(line + "\n", style=BANNER_STYLE)
    return art


def _animate_intro(console: Console, lines: list[str]) -> None:
    """Boot sequence: a scanning loader, then a left-to-right wipe reveal of
    the banner. Plain ASCII, no gradient."""
    boot = "initializing"
    bar_w = 14
    try:
        with Live(console=console, refresh_per_second=60, transient=False) as live:
            # 1. fill a scanner bar
            for step in range(bar_w + 1):
                bar = "█" * step + "░" * (bar_w - step)
                live.update(
                    Padding(Text.assemble(("  ", ""), (bar, "white"),
                                          (f"  {boot}", GREY)), (1, 0, 1, 2))
                )
                time.sleep(0.022)
            time.sleep(0.06)
            # 2. wipe-reveal the banner
            maxw = max(len(ln) for ln in lines)
            for cut in range(0, maxw + 3, 2):
                t = Text()
                for ln in lines:
                    t.append(ln[:cut] + "\n", style=BANNER_STYLE)
                live.update(Padding(t, (1, 0, 0, 2)))
                time.sleep(0.012)
            live.update(Padding(_banner_text(lines), (1, 0, 0, 2)))
    except Exception:  # noqa: BLE001 — never let the intro break startup
        console.print(Padding(_banner_text(lines), (1, 0, 0, 2)))


def print_banner(console: Console, config, cwd: str, animate: bool = True) -> None:
    art = BANNER_WIDE if console.width >= 80 else BANNER
    lines = art.strip("\n").splitlines()
    if animate and console.is_terminal:
        _animate_intro(console, lines)
    else:
        console.print(Padding(_banner_text(lines), (1, 0, 0, 2)))

    console.print(
        Padding(Text("the autonomous agent that learns", style=f"italic {GREY}"), (0, 0, 0, 2))
    )

    _label = {
        "ollama": ("● local", GREEN),
        "anthropic": ("● anthropic", SKY),
        "openai": ("● openai", GREEN),
        "codex": ("● chatgpt", GREEN),
    }.get(config.provider, ("● cloud", SKY))
    model_line = Text.assemble(
        ("model  ", GREY), (config.active_model, "bold white"), ("  ", ""), _label,
    )
    flags = []
    if config.auto:
        flags.append("⚡ auto")
    if config.learning:
        flags.append("✦ learning")
    import platform
    if platform.system() == "Darwin":
        flags.append("🍎 mac access")
    if config.yolo and not config.auto:
        flags.append("yolo")
    meta_line = Text.assemble(
        ("\n", ""),
        (("  ·  ".join(flags)) + "\n", GREY),
        ("cwd    ", GREY), (cwd, FAINT),
    )

    panel = Panel(
        Group(model_line, meta_line),
        box=box.ROUNDED,
        border_style="grey42",
        padding=(0, 2),
        expand=False,
    )

    console.print(Padding(panel, (1, 0, 0, 2)))
    console.print(
        Padding(
            Text.assemble(
                ("type a request  ·  ", FAINT), ("/help", "bold white"),
                (" for commands  ·  ", FAINT), ("/exit", "bold white"), (" to quit", FAINT),
            ),
            (1, 0, 1, 2),
        )
    )


# --- animated "working" spinner ------------------------------------------

_BRAILLE_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class _Pulse:
    """A self-animating Braille spinner. Picks a frame from the current time, so
    Rich's Live auto-refresh animates it with no background thread."""

    def __init__(self, label: str = "working") -> None:
        self.label = label

    def __rich_console__(self, console, options):
        frame = _BRAILLE_FRAMES[int(time.monotonic() * 12) % len(_BRAILLE_FRAMES)]
        yield Padding(
            Text.assemble((frame, f"bold {CYAN}"), (f"  {self.label}", GREY)),
            (0, 0, 0, 2),
        )


# --- streaming assistant view --------------------------------------------


class StreamView:
    """Renders one assistant turn live: an animated pulse while waiting, then a
    dim thinking section, then markdown response text. Falls back to plain
    incremental printing when markdown streaming is disabled."""

    def __init__(self, console: Console, markdown: bool = True, show_thinking: bool = True):
        self.console = console
        self.markdown = markdown
        self.show_thinking = show_thinking
        self._thinking = ""
        self._text = ""
        self._live: Live | None = None
        self._last = 0.0
        self._plain_started = False

    def __enter__(self) -> "StreamView":
        if self.markdown:
            self._live = Live(console=self.console, refresh_per_second=20,
                              vertical_overflow="visible")
            self._live.__enter__()
            self._live.update(_Pulse())  # animate until the first token arrives
        return self

    def _renderable(self):
        parts = []
        if self.show_thinking and self._thinking.strip():
            parts.append(
                Panel(
                    Text(self._thinking.strip(), style=THINKING_STYLE),
                    title=Text("✦ thinking", style=f"italic {GREY}"),
                    title_align="left",
                    box=box.ROUNDED,
                    border_style="grey30",
                    padding=(0, 1),
                    expand=False,
                )
            )
        if self._text:
            parts.append(Padding(Markdown(self._text), (0, 0, 0, 2)))
        if not parts:
            return _Pulse()
        return Group(*parts)

    def _refresh(self, force: bool = False) -> None:
        if not self._live:
            return
        now = time.monotonic()
        if force or now - self._last > 0.07:
            self._live.update(self._renderable())
            self._last = now

    def on_thinking(self, delta: str) -> None:
        self._thinking += delta
        if self.markdown:
            self._refresh()
        elif self.show_thinking:
            if not self._plain_started:
                self.console.print(Text("✦ thinking…", style=f"italic {GREY}"))
                self._plain_started = True
            self.console.print(Text(delta, style=THINKING_STYLE), end="")

    def on_text(self, delta: str) -> None:
        if self.markdown:
            self._text += delta
            self._refresh()
        else:
            self.console.print(Text(delta, style=ASSISTANT_STYLE), end="")

    def __exit__(self, *exc) -> None:
        if self._live:
            self._refresh(force=True)
            self._live.__exit__(*exc)
        else:
            self.console.print()


class NullView:
    """Discards all streamed output (used for sub-agents and reflection)."""

    def on_thinking(self, delta: str) -> None:
        pass

    def on_text(self, delta: str) -> None:
        pass


# --- tool activity log ----------------------------------------------------


def render_tool_call(console: Console, name: str, summary: str) -> None:
    if name.startswith("mcp__"):
        icon = "🔌"
        parts = name.split("__", 2)
        name = f"{parts[1]}·{parts[2]}" if len(parts) == 3 else name  # server·tool
    else:
        icon = TOOL_ICONS.get(name, "◆")
    line = Text("  ")
    line.append(f"{icon} ", style=ACCENT)
    line.append(name, style="bold white")
    if summary:
        line.append("  " + summary, style=GREY)
    console.print(line)


def render_tool_result(console: Console, result: str, is_error: bool = False) -> None:
    lines = result.splitlines() or ["(no output)"]
    shown = lines[:14]
    bar = RED if is_error else "grey35"
    txt = RED if is_error else "grey50"
    body = Text()
    for i, ln in enumerate(shown):
        body.append("  ▏ ", style=bar)
        body.append(ln, style=txt)
        if i < len(shown) - 1:
            body.append("\n")
    if len(lines) > 14:
        body.append("\n")
        body.append("  ▏ ", style=bar)
        body.append(f"… +{len(lines) - 14} more lines", style=FAINT)
    console.print(body)


def render_tool_denied(console: Console, name: str) -> None:
    console.print(Text.assemble(("  ✗ ", RED), ("denied ", f"bold {RED}"), (name, GREY)))


def render_recall(console: Console, n: int) -> None:
    console.print(Text(f"  ◴ recalled {n} {'memory' if n == 1 else 'memories'}",
                       style=f"italic {GREY}"))


def render_learned(console: Console, kind: str, text: str) -> None:
    console.print(Text.assemble(
        ("  ✦ ", VIOLET), ("learned ", f"bold {VIOLET}"),
        (f"{kind} · ", PINK), (text, GREY),
    ))


def render_meta(console: Console, text: str) -> None:
    console.print(Padding(Text(text, style=FAINT), (1, 0, 0, 2)))


def render_compaction(console: Console, before_tokens: int) -> None:
    console.print(Text(f"  ↯ compacted context (~{before_tokens:,} tokens → summary)",
                       style=f"italic {GREY}"))


def render_goal_header(console: Console, goal: str) -> None:
    console.print(
        Padding(
            Panel(
                Text(goal, style="white"),
                title=Text("◎ goal mode", style=f"bold {VIOLET}"),
                title_align="left",
                box=box.ROUNDED,
                border_style=VIOLET,
                padding=(0, 2),
                expand=False,
            ),
            (1, 0, 0, 2),
        )
    )


def render_round(console: Console, rnd: int, total: int) -> None:
    console.print(Padding(Text(f"── round {rnd}/{total} ──", style=f"bold {SKY}"), (1, 0, 0, 2)))


def render_goal_result(console: Console, outcome: str) -> None:
    glyph = {"achieved": ("✓", GREEN), "blocked": ("⚠", AMBER), "incomplete": ("…", GREY)}
    g, c = glyph.get(outcome, ("…", GREY))
    label = {"achieved": "goal achieved", "blocked": "blocked — needs you",
             "incomplete": "ran out of rounds"}.get(outcome, outcome)
    console.print(Padding(Text.assemble((f"{g} ", c), (label, f"bold {c}")), (1, 0, 0, 2)))


def render_todos(console: Console, todos: "list[TodoItem]") -> None:
    if not todos:
        return
    mark = {"pending": "○", "in_progress": "◐", "done": "●"}
    color = {"pending": GREY, "in_progress": AMBER, "done": GREEN}
    rows = Text()
    for i, t in enumerate(todos):
        c = color.get(t.status, GREY)
        rows.append(f"{mark.get(t.status, '○')} ", style=c)
        rows.append(t.text, style=("strike " + GREY) if t.status == "done" else "white")
        if i < len(todos) - 1:
            rows.append("\n")
    done = sum(1 for t in todos if t.status == "done")
    console.print(
        Padding(
            Panel(
                rows,
                title=Text(f"plan · {done}/{len(todos)}", style=f"bold {SKY}"),
                title_align="left",
                box=box.ROUNDED,
                border_style=INDIGO,
                padding=(0, 2),
                expand=False,
            ),
            (0, 0, 0, 2),
        )
    )
