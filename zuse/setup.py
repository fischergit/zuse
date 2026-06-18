"""Interactive setup wizard for Zuse.

The wizard intentionally keeps setup local and simple: it creates the Zuse data
folder, writes the persistent Zuse config, and can maintain a small shell env
file with secrets/placeholders for bridge integrations.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from . import __version__
from .config import CONFIG_DIR, CONFIG_FILE, Config, ensure_dirs, resolve_model

ENV_FILE = CONFIG_DIR / "env"


def _read_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _write_env_file(values: dict[str, str], path: Path = ENV_FILE) -> None:
    ensure_dirs()
    lines = [
        "# Zuse environment file",
        "# Load manually with: source ~/.zuse/env",
        "# install.sh also creates shell snippets that source this file when present.",
        "",
    ]
    for key in sorted(values):
        value = values[key]
        if value:
            escaped = value.replace("'", "'\\''")
            lines.append(f"export {key}='{escaped}'")
    path.write_text("\n".join(lines).rstrip() + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _prompt_secret(console: Console, name: str, current: str = "") -> str:
    shown = "set" if current else "empty"
    value = Prompt.ask(f"{name} [{shown}]", default="", password=True, console=console)
    return current if value == "" else value.strip()


def _setup_provider(console: Console, cfg: Config, env: dict[str, str], *, non_interactive: bool) -> None:
    if non_interactive:
        return
    provider = Prompt.ask(
        "Provider",
        choices=["ollama", "anthropic", "openai", "codex"],
        default=cfg.provider if cfg.provider in {"ollama", "anthropic", "openai", "codex"} else "ollama",
        console=console,
    )
    cfg.provider = provider
    if provider == "ollama":
        cfg.local_model = Prompt.ask("Ollama model", default=cfg.local_model, console=console)
        cfg.ollama_host = Prompt.ask("Ollama host", default=cfg.ollama_host, console=console)
    elif provider == "anthropic":
        cfg.model = resolve_model(Prompt.ask("Claude model", default=cfg.model, console=console))
        env["ANTHROPIC_API_KEY"] = _prompt_secret(console, "ANTHROPIC_API_KEY", env.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", "")))
    elif provider == "openai":
        cfg.openai_model = Prompt.ask("OpenAI model", default=cfg.openai_model, console=console)
        cfg.openai_base_url = Prompt.ask("OpenAI base URL", default=cfg.openai_base_url, console=console)
        env["OPENAI_API_KEY"] = _prompt_secret(console, "OPENAI_API_KEY", env.get("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "")))
    elif provider == "codex":
        cfg.codex_model = Prompt.ask("Codex model", default=cfg.codex_model, console=console)
        console.print("[dim]Run `zuse --login` after setup if Codex OAuth is not signed in yet.[/]")


def _setup_interfaces(console: Console, env: dict[str, str], *, non_interactive: bool) -> None:
    if non_interactive:
        return
    if Confirm.ask("Telegram bot einrichten?", default=False, console=console):
        env["TELEGRAM_BOT_TOKEN"] = _prompt_secret(console, "TELEGRAM_BOT_TOKEN", env.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", "")))
        allowed = Prompt.ask(
            "Erlaubte Telegram Chat-IDs (kommagetrennt, leer = alle)",
            default=env.get("ZUSE_TELEGRAM_ALLOWED_CHAT_IDS", ""),
            console=console,
        )
        env["ZUSE_TELEGRAM_ALLOWED_CHAT_IDS"] = allowed.strip()
    if Confirm.ask("WhatsApp QR/Web Bridge vorbereiten?", default=True, console=console):
        env.setdefault("ZUSE_WHATSAPP_QR_PORT", "8797")
        console.print("[dim]Start später mit `zuse-whatsapp --qr`; dann QR-Code scannen.[/]")
    if Confirm.ask("WhatsApp Cloud API konfigurieren?", default=False, console=console):
        env["ZUSE_WHATSAPP_VERIFY_TOKEN"] = env.get("ZUSE_WHATSAPP_VERIFY_TOKEN") or secrets.token_urlsafe(24)
        env["WHATSAPP_ACCESS_TOKEN"] = _prompt_secret(console, "WHATSAPP_ACCESS_TOKEN", env.get("WHATSAPP_ACCESS_TOKEN", os.environ.get("WHATSAPP_ACCESS_TOKEN", "")))
        env["WHATSAPP_PHONE_NUMBER_ID"] = Prompt.ask("WHATSAPP_PHONE_NUMBER_ID", default=env.get("WHATSAPP_PHONE_NUMBER_ID", ""), console=console)
        env["WHATSAPP_APP_SECRET"] = _prompt_secret(console, "WHATSAPP_APP_SECRET", env.get("WHATSAPP_APP_SECRET", os.environ.get("WHATSAPP_APP_SECRET", "")))


def _maybe_install_playwright(console: Console, *, non_interactive: bool) -> None:
    if non_interactive or not Confirm.ask("Playwright Chromium für Browser-Tools installieren?", default=False, console=console):
        return
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        console.print(f"[yellow]Playwright-Installation übersprungen/fehlgeschlagen:[/] {exc}")


def _print_summary(console: Console, cfg: Config, env: dict[str, str]) -> None:
    table = Table(title="Zuse Setup", box=None, padding=(0, 2))
    table.add_column("Bereich", style="bold cyan")
    table.add_column("Wert")
    table.add_row("Version", __version__)
    table.add_row("Config", str(CONFIG_FILE))
    table.add_row("Env", str(ENV_FILE))
    table.add_row("Provider", f"{cfg.provider} / {cfg.active_model}")
    table.add_row("Telegram", "konfiguriert" if env.get("TELEGRAM_BOT_TOKEN") else "nicht konfiguriert")
    table.add_row("WhatsApp QR", f"Port {env.get('ZUSE_WHATSAPP_QR_PORT', '8797')}")
    console.print(table)


def run_setup(*, non_interactive: bool = False) -> int:
    console = Console()
    ensure_dirs()
    cfg = Config.load()
    env = _read_env_file()

    console.print(Panel.fit("[bold cyan]Zuse Setup[/]\nLokaler Einrichtungsassistent für CLI, WebGUI, Telegram und WhatsApp."))
    _setup_provider(console, cfg, env, non_interactive=non_interactive)
    _setup_interfaces(console, env, non_interactive=non_interactive)
    if not non_interactive:
        cfg.yolo = Confirm.ask("Auto-Approve/Yolo standardmäßig aktivieren?", default=cfg.yolo, console=console)
        cfg.learning = Confirm.ask("Kontinuierliches Lernen aktivieren?", default=cfg.learning, console=console)
    cfg.save()
    _write_env_file(env)
    _maybe_install_playwright(console, non_interactive=non_interactive)
    _print_summary(console, cfg, env)
    console.print("\n[green]✓ Setup fertig.[/] Starte mit `zuse`, `zuse-web`, `zuse-telegram` oder `zuse-whatsapp --qr`.")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Zuse setup wizard")
    parser.add_argument("--non-interactive", action="store_true", help="Create config/env files without prompts")
    parser.add_argument("--print-env", action="store_true", help="Print the env file path and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.print_env:
        print(ENV_FILE)
        return 0
    return run_setup(non_interactive=args.non_interactive)


if __name__ == "__main__":
    raise SystemExit(main())
