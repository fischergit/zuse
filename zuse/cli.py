"""Command-line entry point: interactive REPL and one-shot mode."""

from __future__ import annotations

import argparse
import importlib.util
import os
import platform
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from rich.console import Console
from rich.table import Table
from rich.progress_bar import ProgressBar

from . import __version__, ui
from .agent import Agent
from .config import CONFIG_DIR, Config, ensure_dirs, resolve_model
from .providers import Backend
from .session import list_sessions, load_session, save_session

HISTORY_FILE = CONFIG_DIR / "history"

SLASH_HELP = [
    ("/help", "Show this command list"),
    ("/doctor", "Check Zuse's local setup and optional capabilities"),
    ("/setup", "Run the local setup wizard"),
    ("/selftest", "Run safe checks for Zuse's core local tools"),
    ("/clear", "Clear the conversation (keep settings)"),
    ("/undo", "Revert the last file change Zuse made"),
    ("/goal <text>", "Autonomous mode: work until the goal is achieved & verified"),
    ("/model <name>", "Switch model for the active provider"),
    ("/login", "Sign in with ChatGPT (OpenAI Codex OAuth)"),
    ("/effort <level>", "Set reasoning effort: low|medium|high|xhigh|max (cloud)"),
    ("/thinking", "Toggle visible thinking"),
    ("/learning", "Toggle continuous learning (reflection after each turn)"),
    ("/auto", "Toggle auto mode: act autonomously + auto-approve actions"),
    ("/yolo", "Toggle auto-approve for all tool permissions"),
    ("/tools", "List available tools"),
    ("/mcp", "Show connected MCP servers and their tools"),
    ("/cost", "Show token usage and estimated cost"),
    ("/ratelimit", "Show Codex rate-limit usage when available"),
    ("/memory [dedupe|compact]", "Show or clean learned knowledge"),
    ("/forget", "Clear all learned knowledge"),
    ("/system", "Show the active system prompt"),
    ("/save <name>", "Save the current conversation"),
    ("/load <name>", "Load a saved conversation"),
    ("/sessions", "List saved conversations"),
    ("/exit, /quit", "Quit Zuse"),
]


def _print_help(console: Console) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan")
    table.add_column(style="white")
    for cmd, desc in SLASH_HELP:
        table.add_row(cmd, desc)
    console.print(table)


def _check_ollama(cfg: Config) -> tuple[str, str]:
    try:
        from .providers.ollama_backend import OllamaBackend

        models = OllamaBackend.list_models(cfg.ollama_host)
    except Exception as e:  # noqa: BLE001
        return "fail", f"not reachable at {cfg.ollama_host}: {e}"
    if not models:
        return "warn", "reachable, but no models installed"
    if cfg.local_model not in models:
        resolved = OllamaBackend.resolve_model(cfg.local_model, models)
        return "warn", f"{len(models)} model(s); configured '{cfg.local_model}' resolves to '{resolved}'"
    return "ok", f"{cfg.local_model} available ({len(models)} model(s))"


def _run_doctor(agent: Agent, console: Console) -> None:
    """Print a quick local health check for Zuse and its optional integrations."""
    cfg = agent.config
    rows = [
        ("Python", "ok", platform.python_version()),
        ("Config dir", "ok" if CONFIG_DIR.exists() else "warn", str(CONFIG_DIR)),
        ("Provider", "ok", f"{cfg.provider} / {cfg.active_model}"),
        ("Ollama", *_check_ollama(cfg)),
        (
            "Anthropic key",
            "ok" if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") else "warn",
            "set" if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") else "not set",
        ),
        (
            "OpenAI key",
            "ok" if os.environ.get("OPENAI_API_KEY") else "warn",
            "set" if os.environ.get("OPENAI_API_KEY") else "not set",
        ),
        (
            "macOS computer use",
            "ok" if importlib.util.find_spec("Quartz") else "warn",
            "Quartz installed" if importlib.util.find_spec("Quartz") else "install with pip install -e '.[mac]'",
        ),
        (
            "Browser automation",
            "ok" if importlib.util.find_spec("playwright") else "warn",
            "Playwright installed" if importlib.util.find_spec("playwright") else "install with pip install -e '.[browser]'",
        ),
        ("MCP", "ok" if agent.mcp.servers else "warn", f"{len(agent.mcp.servers)} server(s) connected"),
        ("Knowledge", "ok", f"{len(agent.knowledge.entries)} learned item(s)"),
    ]

    styles = {"ok": "#34D399", "warn": "#FBBF24", "fail": "#F87171"}
    icons = {"ok": "✓", "warn": "!", "fail": "✗"}
    table = Table(title="Zuse doctor", box=None, padding=(0, 2))
    table.add_column("check", style="bold cyan")
    table.add_column("status")
    table.add_column("details", style="white")
    for name, status, detail in rows:
        table.add_row(name, f"[{styles[status]}]{icons[status]} {status}[/]", detail)
    console.print(table)


def _codex_rate_limit_status(agent: Agent) -> dict | None:
    if agent.config.provider != "codex":
        return None
    getter = getattr(agent.backend, "rate_limit_status", None)
    if getter is None:
        return {"provider": "codex", "limits": [], "headers": {}}
    try:
        return getter()
    except Exception as e:  # noqa: BLE001
        return {"provider": "codex", "limits": [], "headers": {}, "error": str(e)}


def _format_reset(seconds: int | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _rate_limit_summary(agent: Agent) -> str:
    status = _codex_rate_limit_status(agent)
    if status is None:
        return "rate-limit: n/a"
    if status.get("error"):
        return "rate-limit: error"
    limits = status.get("limits") or []
    if not limits:
        return "rate-limit: waiting"
    chunks = []
    for limit in limits[:3]:
        name = str(limit.get("name") or "requests")
        used = limit.get("used_percent")
        remaining = limit.get("remaining")
        total = limit.get("limit")
        used_text = "?%" if used is None else f"{int(round(max(0, min(100, used))))}%"
        if remaining is not None and total is not None:
            chunks.append(f"{name} {used_text} ({remaining}/{total})")
        else:
            chunks.append(f"{name} {used_text}")
    return "rate-limit: " + " · ".join(chunks)


def _render_rate_limit_warning(agent: Agent, console: Console, threshold: int = 80) -> None:
    status = _codex_rate_limit_status(agent)
    if not status or status.get("error"):
        return
    warnings = []
    for limit in status.get("limits") or []:
        used = limit.get("used_percent")
        if used is not None and used >= threshold:
            warnings.append(f"{limit.get('name') or 'requests'} {int(round(used))}%")
    if warnings:
        console.print(f"[#FBBF24]Codex rate-limit warning:[/] {' · '.join(warnings)} used")


def _render_rate_limits(agent: Agent, console: Console) -> None:
    status = _codex_rate_limit_status(agent)
    if status is None:
        console.print("[dim]Rate-Limit-Anzeige ist nur für provider=codex verfügbar.[/]")
        return
    if status.get("error"):
        console.print(f"[#F87171]Codex rate-limit error:[/] {status['error']}")
        return
    limits = status.get("limits") or []
    if not limits:
        console.print(
            "[dim]Noch keine Codex-Rate-Limit-Header empfangen. "
            "Starte eine Codex-Anfrage und rufe danach /ratelimit oder /cost auf.[/]"
        )
        headers = status.get("headers") or {}
        if headers:
            console.print("[dim]Raw headers:[/]")
            for key, value in headers.items():
                console.print(f"  [cyan]{key}[/]: {value}")
        return

    table = Table(title="Codex rate limit", box=None, padding=(0, 2))
    table.add_column("limit", style="bold cyan")
    table.add_column("usage")
    table.add_column("used")
    table.add_column("remaining")
    table.add_column("reset", style="dim")
    for limit in limits:
        used = limit.get("used_percent")
        used_value = 0 if used is None else max(0, min(100, int(round(used))))
        bar = ProgressBar(total=100, completed=used_value, width=22)
        used_text = f"{used_value}%" if used is not None else "—"
        remaining = limit.get("remaining")
        total = limit.get("limit")
        remaining_text = f"{remaining if remaining is not None else '?'} / {total if total is not None else '?'}"
        table.add_row(str(limit.get("name") or "requests"), bar, used_text, remaining_text, _format_reset(limit.get("reset_seconds")))
    console.print(table)


def _run_selftest(agent: Agent, console: Console) -> bool:
    """Exercise safe local tool paths without calling a model or external services."""
    from .tools import ToolContext, build_registry, default_tools

    registry = build_registry(default_tools())
    rows: list[tuple[str, str, str]] = []

    def record(name: str, ok: bool, detail: str) -> None:
        rows.append((name, "ok" if ok else "fail", detail))

    with tempfile.TemporaryDirectory(prefix="zuse-selftest-") as tmp:
        tmp_path = Path(tmp)
        base_ctx = agent.ctx
        ctx = ToolContext(
            cwd=tmp_path,
            console=base_ctx.console,
            permissions=base_ctx.permissions,
            config=base_ctx.config,
            knowledge=base_ctx.knowledge,
            shell=base_ctx.shell,
            background=base_ctx.background,
            journal=None,
            browser=base_ctx.browser,
            spawn_subagent=base_ctx.spawn_subagent,
        )

        checks = [
            ("write_file", {"path": "sample.txt", "content": "hello zuse\n"}, "Created"),
            ("read_file", {"path": "sample.txt"}, "hello zuse"),
            (
                "edit_file",
                {"path": "sample.txt", "old_string": "hello", "new_string": "hi"},
                "Edited",
            ),
            ("list_directory", {"path": "."}, "sample.txt"),
            ("glob", {"pattern": "*.txt", "path": "."}, "sample.txt"),
            ("grep", {"pattern": "hi", "path": ".", "glob": "*.txt"}, "sample.txt"),
            ("python", {"code": "print(2 + 3)", "timeout": 10}, "5"),
            ("bash", {"command": f"cd {tmp_path} && pwd", "timeout": 10}, str(tmp_path)),
            (
                "todo_write",
                {"items": [{"text": "selftest", "status": "in_progress"}]},
                "Task list updated",
            ),
        ]

        for tool_name, args, expected in checks:
            try:
                out = registry[tool_name].run(args, ctx)
                text = out.text if hasattr(out, "text") else str(out)
                record(tool_name, expected in text, text.splitlines()[0][:120])
            except Exception as e:  # noqa: BLE001
                record(tool_name, False, f"{type(e).__name__}: {e}")

        bg_id = ""
        try:
            bg_out = registry["run_background"].run({"command": "printf ready; sleep 0.1"}, ctx)
            bg_id = bg_out.split()[3].rstrip(":")
            import time

            time.sleep(0.2)
            logs = registry["bg_logs"].run({"task_id": bg_id, "lines": 5}, ctx)
            record("background", "ready" in logs, logs or bg_out)
        except Exception as e:  # noqa: BLE001
            record("background", False, f"{type(e).__name__}: {e}")
        finally:
            if bg_id:
                try:
                    registry["bg_stop"].run({"task_id": bg_id}, ctx)
                except Exception:  # noqa: BLE001
                    pass

    styles = {"ok": "#34D399", "fail": "#F87171"}
    icons = {"ok": "✓", "fail": "✗"}
    table = Table(title="Zuse selftest", box=None, padding=(0, 2))
    table.add_column("tool", style="bold cyan")
    table.add_column("status")
    table.add_column("details", style="white")
    for name, status, detail in rows:
        table.add_row(name, f"[{styles[status]}]{icons[status]} {status}[/]", detail)
    console.print(table)

    passed = sum(1 for _, status, _ in rows if status == "ok")
    console.print(f"[#34D399]{passed}[/]/{len(rows)} checks passed")
    return passed == len(rows)


def _handle_slash(cmd: str, agent: Agent, console: Console) -> bool:
    """Return True to keep the REPL running, False to exit."""
    parts = cmd.strip().split(maxsplit=1)
    name = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    cfg = agent.config

    if name in ("/exit", "/quit", "/q"):
        return False

    if name == "/help":
        _print_help(console)
    elif name == "/doctor":
        _run_doctor(agent, console)
    elif name == "/setup":
        from .setup import run_setup

        run_setup(non_interactive=False)
        agent.config = Config.load()
        agent.refresh_system()
    elif name == "/selftest":
        _run_selftest(agent, console)
    elif name == "/clear":
        agent.backend.clear()
        agent.permissions.reset_session()
        console.print("[green]Conversation cleared.[/]")
    elif name == "/undo":
        j = agent.journal
        if not j.can_undo():
            console.print("[dim]Nothing to undo.[/]")
        else:
            console.print(f"[green]{j.undo_last()}[/]")
    elif name == "/goal":
        if not arg:
            console.print("Usage: /goal <what you want achieved>")
        else:
            try:
                agent.run_goal(arg)
            except KeyboardInterrupt:
                console.print("\n[#FBBF24]goal mode interrupted[/]")
    elif name == "/model":
        if not arg:
            console.print(f"Active model: [cyan]{cfg.active_model}[/] ([dim]{cfg.provider}[/])")
        elif cfg.is_local:
            cfg.local_model = arg
            agent.backend.model = arg  # type: ignore[attr-defined]
            console.print(f"[green]Local model set to[/] [cyan]{arg}[/]")
        else:
            cfg.model = resolve_model(arg)
            console.print(f"[green]Model set to[/] [cyan]{cfg.model}[/]")
    elif name == "/login":
        from .openai_auth import login

        try:
            login()
            console.print("[#34D399]✓ Signed in with ChatGPT.[/] Restart with "
                          "[bold]zuse --provider codex[/] to use OpenAI's model.")
        except Exception as e:  # noqa: BLE001
            console.print(f"[#F87171]Login failed:[/] {e}")
    elif name == "/effort":
        if cfg.is_local:
            console.print("[dim]Effort applies to cloud models only.[/]")
        elif arg in ("low", "medium", "high", "xhigh", "max"):
            cfg.effort = arg
            console.print(f"[green]Effort set to[/] {arg}")
        else:
            console.print(f"Current effort: {cfg.effort}. Use low|medium|high|xhigh|max")
    elif name == "/thinking":
        cfg.show_thinking = not cfg.show_thinking
        console.print(f"Visible thinking: {'on' if cfg.show_thinking else 'off'}")
    elif name == "/learning":
        cfg.learning = not cfg.learning
        console.print(f"Continuous learning: {'on' if cfg.learning else 'off'}")
    elif name == "/auto":
        cfg.auto = not cfg.auto
        agent.permissions.yolo = cfg.yolo or cfg.auto
        agent.refresh_system()  # add/remove the autonomy directive
        if cfg.auto:
            console.print("[#E879F9]⚡ auto mode ON[/] — Zuse acts autonomously and "
                          "won't ask for routine confirmations.")
        else:
            console.print("auto mode off")
    elif name == "/yolo":
        cfg.yolo = not cfg.yolo
        agent.permissions.yolo = cfg.yolo or cfg.auto
        console.print(f"[yellow]YOLO mode {'ON — tools auto-approved' if cfg.yolo else 'off'}[/]")
    elif name == "/tools":
        table = Table(title="Tools", box=None, padding=(0, 2))
        table.add_column("name", style="bold magenta")
        table.add_column("perm", style="yellow")
        table.add_column("description", style="white")
        for t in agent.tools:
            table.add_row(t.name, "ask" if t.requires_permission else "auto",
                          t.description.split(".")[0][:70])
        if agent.backend.supports_web and cfg.enable_web:
            table.add_row("web_search", "auto", "Server-side web search")
            table.add_row("web_fetch", "auto", "Server-side URL fetch")
        console.print(table)
    elif name == "/mcp":
        from .mcp import MCP_CONFIG

        mgr = agent.mcp
        if not mgr.servers and not mgr.errors:
            console.print(
                "[dim]No MCP servers connected.[/] Configure them in "
                f"[cyan]{MCP_CONFIG}[/] (mcpServers), then restart."
            )
        else:
            for srv in mgr.servers:
                console.print(f"  [bold #34D399]● {srv.name}[/]  [dim]{len(srv.tools)} tools[/]")
                names = ", ".join(t["name"] for t in srv.tools)
                if names:
                    console.print(f"    [grey50]{names[:200]}[/]")
            for srv_name, err in mgr.errors:
                console.print(f"  [#F87171]✗ {srv_name}[/]  [dim]{err[:80]}[/]")
    elif name == "/cost":
        console.print("  " + agent.usage.summary(agent.cost_model))
        if cfg.provider == "codex":
            _render_rate_limits(agent, console)
    elif name in {"/ratelimit", "/rate-limit", "/rate"}:
        _render_rate_limits(agent, console)
    elif name == "/memory":
        store = agent.knowledge
        if arg in {"dedupe", "dedup"}:
            removed = store.dedupe()
            agent.refresh_system()
            console.print(f"[green]Memory dedupe complete:[/] removed {removed} duplicate item(s).")
        elif arg in {"compact", "compress"}:
            compacted = store.compact_preferences()
            deduped = store.dedupe()
            agent.refresh_system()
            console.print(
                f"[green]Memory compact complete:[/] compacted preferences, "
                f"removed {compacted + deduped} noisy/duplicate item(s)."
            )
        elif arg:
            console.print("Usage: /memory [dedupe|compact]")
        elif not store.entries:
            console.print("[dim](nothing learned yet — Zuse learns as you work)[/]")
        else:
            s = store.stats()
            console.print(
                f"[bold]{s['total']} learned[/] · "
                f"{s.get('preference', 0)} pref · {s.get('fact', 0)} fact · "
                f"{s.get('procedure', 0)} proc"
            )
            kind_style = {"preference": "cyan", "fact": "white", "procedure": "green"}
            for kind, title in (
                ("preference", "Preferences"),
                ("fact", "Facts"),
                ("procedure", "Procedures"),
            ):
                entries = [e for e in store.entries if e.kind == kind]
                if not entries:
                    continue
                console.print(f"\n[bold]{title}[/]")
                tag = kind_style.get(kind, "white")
                for e in entries[-20:]:
                    uses = f", uses {e.uses}" if e.uses else ""
                    console.print(f"  [{tag}]{kind[:4]}[/] {e.text}  [dim]({e.created}{uses})[/]")
    elif name == "/forget":
        n = agent.knowledge.clear()
        agent.refresh_system()
        console.print(f"[green]Forgot {n} learned items.[/]")
    elif name == "/system":
        console.print(f"[dim]{agent.system}[/]")
    elif name == "/save":
        if not arg:
            console.print("Usage: /save <name>")
        else:
            path = save_session(arg, agent.backend.export(), cfg.provider, cfg.active_model)
            console.print(f"[green]Saved[/] → {path}")
    elif name == "/load":
        if not arg:
            console.print("Usage: /load <name>")
        else:
            try:
                data = load_session(arg)
            except FileNotFoundError:
                console.print(f"[red]No session named[/] {arg}")
                return True
            if data.get("provider") and data["provider"] != cfg.provider:
                console.print(
                    f"[red]Provider mismatch:[/] session is '{data['provider']}', "
                    f"current is '{cfg.provider}'. Cannot load."
                )
                return True
            agent.backend.load(data["messages"])
            console.print(f"[green]Loaded[/] {arg} ({len(data['messages'])} messages)")
    elif name == "/sessions":
        rows = list_sessions()
        if not rows:
            console.print("[dim](no saved sessions)[/]")
        else:
            for n, prov, when in rows:
                console.print(f"  [cyan]{n}[/]  [magenta]{prov}[/]  [dim]{when}[/]")
    else:
        console.print(f"[red]Unknown command:[/] {name}. Try /help")
    return True


def _make_session(agent: Agent | None = None):
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.styles import Style

        ensure_dirs()
        style = Style.from_dict({"arrow": "#22d3ee bold", "toolbar": "#6b7280", "": "#e5e7eb"})
        kwargs = {}
        if agent is not None:
            kwargs["bottom_toolbar"] = lambda: [("class:toolbar", _rate_limit_summary(agent))]
        return PromptSession(history=FileHistory(str(HISTORY_FILE)), style=style, **kwargs)
    except Exception:  # noqa: BLE001
        return None


def _read_input(session, console: Console) -> str | None:
    # prompt_toolkit runs its own asyncio loop via asyncio.run(), which raises
    # "cannot be called from a running event loop" if one is already running in
    # this thread. Playwright's sync API keeps an event loop alive in the main
    # thread for as long as a browser session is open, so once a browser tool has
    # been used, fall back to builtin input() (which needs no event loop).
    import asyncio

    loop_running = False
    try:
        asyncio.get_running_loop()
        loop_running = True
    except RuntimeError:
        pass

    if session is not None and not loop_running:
        try:
            from prompt_toolkit.formatted_text import FormattedText

            return session.prompt(FormattedText([("class:arrow", "\n❯ ")]))
        except (EOFError, KeyboardInterrupt):
            return None
        except Exception:  # noqa: BLE001 — fall back to a plain prompt below
            pass
    try:
        return console.input("\n[bold #22d3ee]❯ [/]")
    except (EOFError, KeyboardInterrupt):
        return None


def run_repl(agent: Agent, console: Console) -> None:
    ui.print_banner(console, agent.config, str(Path.cwd()),
                    mcp_servers=len(agent.mcp.servers), context_limit=agent._compact_threshold())
    if agent.project:
        console.print(f"  [grey42]📋 loaded project instructions ({len(agent.project)} chars)[/]")
    session = _make_session(agent)
    while True:
        text = _read_input(session, console)
        if text is None:
            break
        text = text.strip()
        if not text:
            continue
        if text.startswith("/"):
            if not _handle_slash(text, agent, console):
                break
            continue
        try:
            agent.run_turn(text)
            _render_rate_limit_warning(agent, console)
        except KeyboardInterrupt:
            console.print("\n[#FBBF24]interrupted[/]")
        except Exception as e:  # noqa: BLE001
            console.print(f"[#F87171]error:[/] {type(e).__name__}: {e}")
    agent.shutdown()
    ui.render_meta(console, agent.usage.summary(agent.cost_model))
    if agent.config.provider == "codex":
        _render_rate_limits(agent, console)
    console.print("[#22d3ee]✦ until next time.[/]")


# -- provider setup --------------------------------------------------------


def _decide_provider(args, cfg: Config) -> str:
    if args.provider:
        return args.provider
    if args.local:
        return "ollama"
    # Honor an explicitly-saved provider preference (ollama/openai/codex).
    if cfg.provider != "anthropic":
        return cfg.provider
    # Provider is the default 'anthropic': use it only if a key is present,
    # otherwise fall back to the local backend ("runs locally first").
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "anthropic"
    return "ollama"


def _setup_backend(cfg: Config, console: Console) -> Callable[[], Backend] | None:
    """Validate the provider and return a backend factory, or None on failure."""
    if cfg.provider == "ollama":
        from .providers.ollama_backend import OllamaBackend

        try:
            available = OllamaBackend.list_models(cfg.ollama_host)
        except Exception:  # noqa: BLE001
            console.print(
                f"[red]Cannot reach Ollama at[/] {cfg.ollama_host}.\n"
                "  Install it from https://ollama.com, then run [bold]ollama serve[/]."
            )
            return None
        if not available:
            console.print(
                "[red]No local models installed.[/] Pull one first, e.g.:\n"
                "  [bold]ollama pull qwen3[/]   (or llama3.1, qwen2.5-coder, mistral-nemo)"
            )
            return None
        resolved = OllamaBackend.resolve_model(cfg.local_model, available)
        if resolved != cfg.local_model:
            console.print(
                f"[dim]Model '{cfg.local_model}' not found; using "
                f"'[cyan]{resolved}[/]' from your installed models.[/]"
            )
        cfg.local_model = resolved
        return lambda: OllamaBackend(cfg)

    if cfg.provider == "openai":
        from .providers.openai_backend import OpenAIBackend
        from .config import PRICING

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            console.print(
                "[red]No OPENAI_API_KEY set.[/] Export it, or use "
                "[bold]--provider codex[/] + [bold]zuse --login[/] to sign in with ChatGPT."
            )
            return None
        cost_model = cfg.openai_model if cfg.openai_model in PRICING else None
        return lambda: OpenAIBackend(cfg, api_key, cfg.openai_base_url, cfg.openai_model, cost_model)

    if cfg.provider == "codex":
        from .openai_auth import logged_in
        from .providers.codex_backend import CodexBackend

        if not logged_in():
            console.print(
                "[red]Not signed in with ChatGPT.[/] Run [bold]zuse --login[/] first "
                "(opens OpenAI OAuth in your browser)."
            )
            return None
        return lambda: CodexBackend(cfg, cfg.codex_model)

    # Anthropic
    try:
        import anthropic
    except ImportError:
        console.print("[red]The 'anthropic' package is not installed.[/] pip install anthropic")
        return None
    try:
        client = anthropic.Anthropic()
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Could not initialize the Anthropic client:[/] {e}")
        console.print("Set ANTHROPIC_API_KEY, or run with [bold]--local[/] to use Ollama.")
        return None
    from .providers.anthropic_backend import AnthropicBackend

    return lambda: AnthropicBackend(client, cfg)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="zuse", description="Zuse — autonomous terminal AI agent")
    p.add_argument("prompt", nargs="*", help="Run a single prompt non-interactively, then exit.")
    p.add_argument("-m", "--model", help="Model name/tag for the active provider.")
    p.add_argument("--local", action="store_true", help="Use a local model via Ollama.")
    p.add_argument("--provider", choices=["anthropic", "ollama", "openai", "codex"],
                   help="Force a provider.")
    p.add_argument("--login", action="store_true",
                   help="Sign in with ChatGPT (OpenAI Codex OAuth) and exit.")
    p.add_argument("--ollama-host", help="Ollama base URL (default http://localhost:11434).")
    p.add_argument("--openai-base-url", help="OpenAI-compatible base URL (default OpenAI).")
    p.add_argument("--list-models", action="store_true", help="List local Ollama models and exit.")
    p.add_argument("--doctor", action="store_true", help="Check Zuse's local setup and optional capabilities, then exit.")
    p.add_argument("--setup", action="store_true", help="Run Zuse's local setup wizard, then exit.")
    p.add_argument("--selftest", action="store_true", help="Run safe checks for Zuse's core local tools, then exit.")
    p.add_argument("-e", "--effort", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--auto", action="store_true",
                   help="Autonomous mode: act decisively and auto-approve actions.")
    p.add_argument("--yolo", action="store_true", help="Auto-approve all tool permissions.")
    p.add_argument("--no-thinking", action="store_true", help="Disable extended thinking.")
    p.add_argument("--no-web", action="store_true", help="Disable web search/fetch tools.")
    p.add_argument("--no-markdown", action="store_true", help="Disable live markdown streaming.")
    p.add_argument("--browser-window", action="store_true",
                   help="Show a visible browser window (default: headless).")
    p.add_argument("--no-learning", action="store_true", help="Disable continuous learning.")
    p.add_argument("--embed-model", help="Ollama embedding model for semantic recall (optional).")
    p.add_argument("-v", "--version", action="version", version=f"zuse {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    ensure_dirs()

    cfg = Config.load()
    if args.ollama_host:
        cfg.ollama_host = args.ollama_host
    if args.effort:
        cfg.effort = args.effort
    if args.yolo:
        cfg.yolo = True
    if args.auto:
        cfg.auto = True
    if args.no_thinking:
        cfg.thinking = False
    if args.no_web:
        cfg.enable_web = False
    if args.no_markdown:
        cfg.stream_markdown = False
    if args.browser_window:
        cfg.browser_headless = False
    if args.no_learning:
        cfg.learning = False
    if args.embed_model:
        cfg.embed_model = args.embed_model
    if args.openai_base_url:
        cfg.openai_base_url = args.openai_base_url

    console = ui.make_console()

    if args.login:
        from .openai_auth import login

        try:
            login()
            console.print("[#34D399]✓ Signed in with ChatGPT.[/] Use "
                          "[bold]zuse --provider codex[/] to chat with their model.")
            return 0
        except Exception as e:  # noqa: BLE001
            console.print(f"[#F87171]Login failed:[/] {e}")
            return 1

    if args.setup:
        from .setup import run_setup

        return run_setup(non_interactive=not sys.stdin.isatty())

    if args.list_models:
        from .providers.ollama_backend import OllamaBackend

        try:
            for m in OllamaBackend.list_models(cfg.ollama_host):
                console.print(f"  [cyan]{m}[/]")
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]Cannot reach Ollama:[/] {e}")
            return 1
        return 0

    cfg.provider = _decide_provider(args, cfg)
    if args.model:
        if cfg.provider == "ollama":
            cfg.local_model = args.model
        elif cfg.provider == "openai":
            cfg.openai_model = args.model
        elif cfg.provider == "codex":
            cfg.codex_model = args.model
        else:
            cfg.model = resolve_model(args.model)

    if args.doctor:
        doctor_agent = SimpleNamespace(
            config=cfg,
            mcp=SimpleNamespace(servers=[]),
            knowledge=SimpleNamespace(entries=[]),
        )
        _run_doctor(doctor_agent, console)  # type: ignore[arg-type]
        return 0

    if args.selftest:
        cfg.yolo = True
        from .journal import EditJournal
        from .knowledge import KnowledgeStore
        from .shell import BackgroundManager, ShellSession
        from .tools import ToolContext

        selftest_agent = SimpleNamespace(
            ctx=ToolContext(
                cwd=Path.cwd(),
                console=console,
                permissions=SimpleNamespace(yolo=True),
                config=cfg,
                knowledge=KnowledgeStore(CONFIG_DIR / "selftest-knowledge.jsonl"),
                shell=ShellSession(Path.cwd()),
                background=BackgroundManager(CONFIG_DIR / "selftest-bg"),
                journal=EditJournal(),
            )
        )
        try:
            return 0 if _run_selftest(selftest_agent, console) else 1  # type: ignore[arg-type]
        finally:
            selftest_agent.ctx.shell.kill()
            selftest_agent.ctx.background.shutdown()

    factory = _setup_backend(cfg, console)
    if factory is None:
        return 1

    agent = Agent(factory, cfg, console)

    if args.prompt:
        prompt = " ".join(args.prompt)
        try:
            agent.run_turn(prompt)
            _render_rate_limit_warning(agent, console)
        except KeyboardInterrupt:
            console.print("\n[#FBBF24]interrupted[/]")
            agent.shutdown()
            return 130
        agent.shutdown()
        ui.render_meta(console, agent.usage.summary(agent.cost_model))
        if agent.config.provider == "codex":
            _render_rate_limits(agent, console)
        return 0

    run_repl(agent, console)
    return 0


if __name__ == "__main__":
    sys.exit(main())
