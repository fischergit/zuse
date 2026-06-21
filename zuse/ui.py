"""Terminal rendering: clean banner, streaming view, tool log, todos."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from rich import box
from rich.columns import Columns
from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .agentpool import DONE, FAILED, QUEUED, RUNNING

if TYPE_CHECKING:
    from .agentpool import AgentRegistry, AgentRun
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

# Startup logo.
BANNER = r"""
 ______     __  __     ______     ______    
/\___  \   /\ \/\ \   /\  ___\   /\  ___\   
\/_/  /__  \ \ \_\ \  \ \___  \  \ \  __\   
  /\_____\  \ \_____\  \/\_____\  \ \_____\ 
  \/_____/   \/_____/   \/_____/   \/_____/
"""

BANNER_SMALL = "ZUSE"

TOOL_ICONS = {
    "read_file": "read", "write_file": "write", "edit_file": "edit", "list_directory": "ls",
    "glob": "find", "grep": "grep", "bash": "sh", "python": "py", "todo_write": "plan",
    "remember": "memo", "task": "agent", "applescript": "mac", "open": "open",
    "clipboard_read": "clip", "clipboard_write": "clip", "screenshot": "shot",
    "notify": "notify", "system_info": "sys", "web_search": "web", "web_fetch": "web",
    "screen": "screen", "mouse_click": "click", "mouse_move": "move", "type_text": "type",
    "key_press": "key", "run_background": "run", "bg_logs": "logs", "bg_stop": "stop",
    "bg_list": "jobs", "browser_open": "browser", "browser_read": "read", "browser_links": "links",
    "browser_click": "click", "browser_type": "type", "browser_screenshot": "shot",
}


def make_console() -> Console:
    return Console()


def _banner_text(lines: list[str]) -> Text:
    art = Text()
    for line in lines:
        art.append(line + "\n", style=BANNER_STYLE)
    return art


def _animate_intro(console: Console, lines: list[str]) -> None:
    """Boot sequence: a braille spinner, then a left-to-right wipe-reveal of the logo."""
    try:
        with Live(console=console, refresh_per_second=60, transient=False) as live:
            # 1. brief braille "initializing" spinner
            for k in range(16):
                frame = _BRAILLE_FRAMES[k % len(_BRAILLE_FRAMES)]
                live.update(Padding(
                    Text.assemble((frame, f"bold {CYAN}"), ("  initializing zuse", GREY)),
                    (1, 0, 1, 2)))
                time.sleep(0.035)
            # 2. wipe-reveal the logo, left to right
            maxw = max(len(ln) for ln in lines)
            for cut in range(0, maxw + 3, 3):
                t = Text()
                for ln in lines:
                    t.append(ln[:cut] + "\n", style=BANNER_STYLE)
                live.update(Padding(t, (1, 0, 0, 2)))
                time.sleep(0.012)
            live.update(Padding(_banner_text(lines), (1, 0, 0, 2)))
    except Exception:  # noqa: BLE001 — never let the intro break startup
        console.print(Padding(_banner_text(lines), (1, 0, 0, 2)))


def print_banner(console: Console, config, cwd: str, animate: bool = True,
                 mcp_servers: int = 0, context_limit: int | None = None) -> None:
    from . import __version__

    art = BANNER if console.width >= 56 else BANNER_SMALL
    lines = art.strip("\n").splitlines()
    if animate and console.is_terminal and console.width >= 56:
        _animate_intro(console, lines)
    else:
        console.print(Padding(_banner_text(lines), (1, 0, 0, 2)))

    provider_label = {
        "ollama": "Ollama",
        "anthropic": "Anthropic",
        "openai": "OpenAI",
        "codex": "ChatGPT",
    }.get(config.provider, config.provider)
    provider_color = {
        "ollama": GREEN, "anthropic": SKY, "openai": GREEN, "codex": GREEN,
    }.get(config.provider, SKY)

    home = str(Path.home())
    cwd_disp = "~" + cwd[len(home):] if cwd.startswith(home) else cwd

    def status(value: bool) -> Text:
        return Text.assemble(("● ", GREEN if value else GREY), ("on" if value else "off", "white"))

    if config.auto:
        mode = Text("auto", style=AMBER)
    elif config.yolo:
        mode = Text("yolo", style=RED)
    else:
        mode = Text("ask", style="white")

    if not config.compact:
        context = Text("off", style=GREY)
    else:
        threshold = context_limit or config.compact_threshold or (
            5500 if config.is_local else 140000)
        context = Text(f"~{threshold:,}", style=FAINT)

    def kv(label: str, value) -> Text:
        text = Text()
        text.append(label, style=GREY)
        text.append("  ")
        if isinstance(value, Text):
            text.append_text(value)
        else:
            text.append(str(value), style="white")
        return text

    left = Group(
        Text.assemble(("Zuse ", f"bold {CYAN}"), (f"v{__version__}", GREY)),
        Text("autonomous coding agent", style=FAINT),
    )
    right = Columns(
        [
            kv("model", Text(config.active_model, style="bold white")),
            kv("provider", Text(provider_label, style=provider_color)),
            kv("cwd", Text(cwd_disp, style=FAINT)),
            kv("mode", mode),
            kv("effort", Text(config.effort, style=FAINT)),
            kv("context", context),
            kv("thinking", status(config.thinking)),
            kv("learning", status(config.learning)),
            kv("web", status(config.enable_web)),
            kv("mcp", Text(str(mcp_servers) if mcp_servers else "none", style=GREEN if mcp_servers else GREY)),
        ],
        equal=True,
        expand=False,
    )

    panel = Panel(
        Group(left, Padding(right, (1, 0, 0, 0))),
        box=box.SIMPLE,
        border_style="grey35",
        padding=(1, 2),
        expand=True,
    )
    console.print(Padding(panel, (0, 0, 0, 2)))
    console.print(
        Padding(
            Text.assemble(
                ("Enter prompt  ", FAINT), ("/help", f"bold {CYAN}"),
                (" for commands  ", FAINT), ("/exit", f"bold {CYAN}"),
                (" to quit", FAINT),
            ),
            (0, 0, 1, 3),
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


def render_answer(console: Console, text: str) -> None:
    """Print the assistant's final answer as a 'zuse' markdown block."""
    console.print(
        Padding(
            Group(
                Text("zuse", style=f"bold {CYAN}"),
                Padding(Markdown(text, code_theme="monokai"), (0, 0, 0, 2)),
            ),
            (1, 0, 0, 2),
        )
    )


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
            # Keep the live area transient and print the final answer once on exit.
            # Some terminals/log sinks don't reliably erase tall live renderables;
            # without this, each refresh can leave another "◆ zuse" block behind.
            self._live = Live(
                console=self.console,
                refresh_per_second=20,
                vertical_overflow="ellipsis",
                transient=True,
            )
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
            block = Group(
                Text("zuse", style=f"bold {CYAN}"),
                Padding(Markdown(self._text, code_theme="monokai"), (0, 0, 0, 2)),
            )
            parts.append(Padding(block, (1, 0, 0, 2)))
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
            self._live.__exit__(*exc)
            if self._text:
                render_answer(self.console, self._text)
        else:
            self.console.print()


class NullView:
    """Discards all streamed output (used for sub-agents and reflection)."""

    def on_thinking(self, delta: str) -> None:
        pass

    def on_text(self, delta: str) -> None:
        pass


# --- live multi-agent crew dashboard -------------------------------------


def _trunc(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _progress_bar(fraction: float, width: int = 10) -> str:
    fraction = max(0.0, min(1.0, fraction))
    filled = int(round(fraction * width))
    return "▰" * filled + "▱" * (width - filled)


_STATUS_GLYPH = {QUEUED: ("○", GREY), RUNNING: ("◐", CYAN), DONE: ("●", GREEN), FAILED: ("✗", RED)}


class TurnProgress:
    """Compact, animated one-line indicator of which agent is running and how far
    along it is — shown in place of the verbose tool/stream log in quiet mode
    (config.show_actions = False). Reads the live todo list for 'how far'; the
    spinner animates from the clock via the Live's auto-refresh, so it keeps
    moving even while the model call blocks."""

    def __init__(
        self, console: Console, todos: "list[TodoItem]", label: str = "zuse", step: int = 0
    ) -> None:
        self.console = console
        self.todos = todos
        self.label = label
        self.step = step
        self.activity = "thinking…"
        self.started = time.monotonic()
        self._live: Live | None = None

    def __enter__(self) -> "TurnProgress":
        self._live = Live(self, console=self.console, refresh_per_second=12, transient=True)
        self._live.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        if self._live:
            self._live.__exit__(*exc)
            self._live = None

    def update(self, activity: str | None = None, step: int | None = None) -> None:
        if activity is not None:
            self.activity = activity
        if step is not None:
            self.step = step

    def __rich_console__(self, console, options):
        frame = _BRAILLE_FRAMES[int(time.monotonic() * 12) % len(_BRAILLE_FRAMES)]
        total = len(self.todos)
        done = sum(1 for t in self.todos if t.status == "done")
        line = Text()
        line.append(frame + " ", style=f"bold {CYAN}")
        line.append(self.label, style="bold white")
        line.append("  " + _trunc(self.activity, 44), style=GREY)
        if total:
            pct = round(done / total * 100)
            line.append("   " + _progress_bar(done / total, 8), style=CYAN)
            line.append(f" {pct}%", style=f"bold {CYAN}")
            line.append(f" {done}/{total}", style=FAINT)
        elif self.step:
            line.append(f"   step {self.step}", style=FAINT)
        line.append(f"  · {time.monotonic() - self.started:.0f}s", style=FAINT)
        yield Padding(line, (0, 0, 0, 2))


class CrewDashboard:
    """Live panel showing every specialist sub-agent in a crew — its status,
    progress, and current activity — refreshing in place while they run.

    Mirrors `StreamView`'s transient `Live` so the refreshing area never stacks;
    on exit it prints one static summary so the finished crew stays on screen.
    The renderable reads a fresh `registry.snapshot()` each refresh and animates
    the running spinner from the clock (no background thread)."""

    def __init__(self, console: Console, registry: "AgentRegistry", goal: str = "") -> None:
        self.console = console
        self.registry = registry
        self.goal = goal
        self._live: Live | None = None

    def __enter__(self) -> "CrewDashboard":
        self._live = Live(
            self,
            console=self.console,
            refresh_per_second=12,
            transient=True,
            vertical_overflow="visible",
        )
        self._live.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        if self._live:
            self._live.__exit__(*exc)
            self._live = None
        self.console.print(Padding(self._panel(final=True), (1, 0, 0, 2)))

    def __rich_console__(self, console, options):
        yield Padding(self._panel(final=False), (1, 0, 0, 2))

    def _row(self, run: "AgentRun", final: bool) -> tuple[Text, ...]:
        bar_color = GREEN if run.status == DONE else RED if run.status == FAILED else CYAN

        if run.status == RUNNING and not final:
            frame = _BRAILLE_FRAMES[int(time.monotonic() * 12) % len(_BRAILLE_FRAMES)]
            glyph = Text(frame, style=f"bold {CYAN}")
        else:
            ch, col = _STATUS_GLYPH.get(run.status, ("○", GREY))
            glyph = Text(ch, style=col)

        name = Text()
        name.append(_trunc(run.role, 16), style="bold white")
        if run.title and run.title != run.role:
            name.append("  " + _trunc(run.title, 30), style=FAINT)

        bar = Text(_progress_bar(run.fraction), style=bar_color)
        percent = Text(f"{run.percent:>3}%", style=f"bold {bar_color}")

        if run.status == FAILED:
            activity = Text(_trunc(run.error or "failed", 46), style=RED)
        elif run.status == DONE:
            activity = Text("done", style=GREEN)
        else:
            activity = Text(_trunc(run.activity or "…", 46), style=GREY)

        elapsed = Text(f"{run.elapsed:3.0f}s", style=FAINT)
        return glyph, name, bar, percent, activity, elapsed

    def _panel(self, final: bool) -> Panel:
        runs = self.registry.snapshot()
        grid = Table.grid(padding=(0, 2), expand=True)
        grid.add_column(no_wrap=True)              # status glyph
        grid.add_column(no_wrap=True)              # role + title
        grid.add_column(no_wrap=True)              # progress bar
        grid.add_column(no_wrap=True, justify="right")  # percent
        grid.add_column(ratio=1)                   # current activity
        grid.add_column(no_wrap=True, justify="right")  # elapsed
        if runs:
            for run in runs:
                grid.add_row(*self._row(run, final))
        else:
            grid.add_row(Text("…", style=GREY), Text("starting crew", style=FAINT),
                         Text(""), Text(""), Text(""), Text(""))

        counts = {QUEUED: 0, RUNNING: 0, DONE: 0, FAILED: 0}
        for run in runs:
            counts[run.status] = counts.get(run.status, 0) + 1
        overall = round(sum(r.fraction for r in runs) / len(runs) * 100) if runs else 0
        footer = Text()
        footer.append(f"{overall}% overall", style=f"bold {CYAN}")
        footer.append("   ·  ", style=FAINT)
        footer.append(f"{counts[RUNNING]} running", style=CYAN)
        footer.append("  ·  ", style=FAINT)
        footer.append(f"{counts[QUEUED]} queued", style=GREY)
        footer.append("  ·  ", style=FAINT)
        footer.append(f"{counts[DONE]} done", style=GREEN)
        if counts[FAILED]:
            footer.append("  ·  ", style=FAINT)
            footer.append(f"{counts[FAILED]} failed", style=RED)
        total_elapsed = max((r.elapsed for r in runs), default=0.0)
        footer.append(f"   {total_elapsed:.0f}s", style=FAINT)

        title = Text.assemble(("⛓ crew", f"bold {VIOLET}"), (f"  {len(runs)} agents", FAINT))
        if self.goal:
            title.append("  ·  " + _trunc(self.goal, 40), style=FAINT)
        return Panel(
            Group(grid, Padding(footer, (1, 0, 0, 0))),
            title=title,
            title_align="left",
            box=box.ROUNDED,
            border_style=VIOLET,
            padding=(1, 2),
            expand=False,
        )


# --- tool activity log ----------------------------------------------------


def render_tool_call(console: Console, name: str, summary: str) -> None:
    if name.startswith("mcp__"):
        icon = "mcp"
        parts = name.split("__", 2)
        name = f"{parts[1]}·{parts[2]}" if len(parts) == 3 else name  # server·tool
    else:
        icon = TOOL_ICONS.get(name, "tool")
    line = Text("  ")
    line.append("• ", style=ACCENT)
    line.append(icon, style=FAINT)
    line.append(" ")
    line.append(name, style="bold white")
    if summary:
        line.append("  " + summary, style=FAINT)
    console.print(line)


RAIL = "#475569"  # soft slate for the tool-output gutter


def render_tool_result(console: Console, result: str, is_error: bool = False) -> None:
    lines = result.splitlines() or ["(no output)"]
    shown = lines[:14]
    bar = RED if is_error else RAIL
    txt = RED if is_error else "grey50"
    body = Text()
    for i, ln in enumerate(shown):
        body.append("    ▏ ", style=bar)
        body.append(ln, style=txt)
        if i < len(shown) - 1:
            body.append("\n")
    if len(lines) > 14:
        body.append("\n")
        body.append("    ▏ ", style=bar)
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
