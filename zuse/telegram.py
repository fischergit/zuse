"""Telegram Bot bridge for Zuse.

This module runs a small long-polling Telegram bot that forwards incoming text
messages to one persistent Zuse Agent and sends the answers back via the Telegram
Bot API. It intentionally uses only the Python standard library so the bridge is
easy to set up: create a bot with @BotFather, export the token, start Zuse.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from .agent import Agent
from .cli import _decide_provider, _setup_backend
from .config import Config, ensure_dirs, resolve_model
from . import ui


@dataclass(frozen=True)
class TelegramMessage:
    """A normalized incoming Telegram text message."""

    update_id: int
    message_id: int
    chat_id: int
    sender_id: int
    text: str
    username: str = ""


@dataclass(frozen=True)
class TelegramSettings:
    """Settings for Telegram Bot API."""

    bot_token: str
    allowed_chat_ids: tuple[int, ...] = ()
    api_base: str = "https://api.telegram.org"

    @classmethod
    def from_env(cls) -> "TelegramSettings":
        allowed = tuple(
            int(s.strip())
            for s in os.environ.get("ZUSE_TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
            if s.strip()
        )
        return cls(
            bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            allowed_chat_ids=allowed,
            api_base=os.environ.get("TELEGRAM_API_BASE", "https://api.telegram.org"),
        )

    def validate(self) -> None:
        if not self.bot_token:
            raise RuntimeError("Missing environment variable: TELEGRAM_BOT_TOKEN")


class TelegramClient:
    def __init__(self, settings: TelegramSettings) -> None:
        self.settings = settings
        self.base_url = f"{settings.api_base.rstrip('/')}/bot{settings.bot_token}"

    def get_me(self) -> dict[str, Any]:
        return self._request("getMe")

    def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        data = self._request("getUpdates", payload, timeout=timeout + 10)
        return list(data.get("result", []))

    def send_text(self, chat_id: int, body: str, reply_to_message_id: int | None = None) -> None:
        """Send a Telegram text message, chunking long answers."""

        for chunk in _chunks(body.strip() or "(keine Antwort)", 3900):
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            }
            if reply_to_message_id is not None:
                payload["reply_parameters"] = {"message_id": reply_to_message_id}
            self._request("sendMessage", payload)
            reply_to_message_id = None

    def _request(self, method: str, payload: dict[str, Any] | None = None, timeout: int = 30) -> dict[str, Any]:
        url = f"{self.base_url}/{method}"
        data = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode()
        req = Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
        try:
            with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed Telegram API URL
                decoded = json.loads(resp.read().decode() or "{}")
        except HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise RuntimeError(f"Telegram API error {e.code}: {detail}") from e
        except URLError as e:
            raise RuntimeError(f"Telegram API request failed: {e}") from e
        if not decoded.get("ok", False):
            raise RuntimeError(f"Telegram API error: {decoded}")
        return decoded


class ZuseTelegramBridge:
    """Thread-safe wrapper around one Zuse Agent conversation."""

    def __init__(self, agent: Agent, client: TelegramClient, settings: TelegramSettings) -> None:
        self.agent = agent
        self.client = client
        self.settings = settings
        self._lock = threading.Lock()
        self._seen: set[int] = set()

    def allowed(self, chat_id: int) -> bool:
        return not self.settings.allowed_chat_ids or chat_id in self.settings.allowed_chat_ids

    def handle(self, msg: TelegramMessage) -> None:
        if msg.update_id in self._seen:
            return
        self._seen.add(msg.update_id)
        if not self.allowed(msg.chat_id):
            self.client.send_text(
                msg.chat_id,
                f"Dieser Telegram-Chat ist nicht freigeschaltet. Chat-ID: {msg.chat_id}",
                msg.message_id,
            )
            return
        with self._lock:
            try:
                answer = self.agent.run_turn(msg.text) or "Fertig."
            except Exception as e:  # noqa: BLE001
                answer = f"Fehler in Zuse: {type(e).__name__}: {e}"
        self.client.send_text(msg.chat_id, answer, msg.message_id)


def _chunks(text: str, limit: int) -> list[str]:
    """Split Telegram messages without cutting paragraphs when possible.

    Telegram rejects messages above its length limit. Prefer splitting at newline
    boundaries for readability, but still hard-split very long lines.
    """

    if limit <= 0:
        raise ValueError("limit must be positive")

    text = text or ""
    if not text:
        return [""]

    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if current:
                chunks.append(current.rstrip("\n"))
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) >= limit:
            if current:
                chunks.append(current.rstrip("\n"))
                current = line
            else:
                current += line
        else:
            current += line
    if current or not chunks:
        chunks.append(current.rstrip("\n"))
    return chunks


def extract_text_message(update: dict[str, Any]) -> TelegramMessage | None:
    """Extract a normal text message from a Telegram getUpdates item."""

    message = update.get("message") or {}
    text = str(message.get("text") or "").strip()
    if not text:
        return None
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    if sender.get("is_bot"):
        return None
    update_id = update.get("update_id")
    message_id = message.get("message_id")
    chat_id = chat.get("id")
    sender_id = sender.get("id") or 0
    if update_id is None or message_id is None or chat_id is None:
        return None
    username = sender.get("username") or sender.get("first_name") or ""
    return TelegramMessage(
        update_id=int(update_id),
        message_id=int(message_id),
        chat_id=int(chat_id),
        sender_id=int(sender_id),
        text=text,
        username=str(username),
    )


def run_terminal_control_loop(bridge: ZuseTelegramBridge, console: Console) -> None:
    """Let the user inject turns into the same Telegram-backed agent session."""

    console.print(
        "[#22d3ee]Lokale Eingriffe sind aktiv.[/] Tippe hier Nachrichten in dieselbe "
        "Zuse-Session. Befehle: [bold]/quit[/], [bold]/clear[/], [bold]/cost[/]."
    )
    while True:
        try:
            text = Prompt.ask("[bold #22d3ee]lokal ❯[/]", default="", console=console).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[#FBBF24]Lokale Eingabe beendet; Telegram läuft weiter bis Ctrl+C.[/]")
            return
        if not text:
            continue
        if text in {"/quit", "/exit", "/q"}:
            raise KeyboardInterrupt
        if text == "/clear":
            bridge.agent.backend.clear()
            bridge.agent.permissions.reset_session()
            console.print("[green]Conversation cleared.[/]")
            continue
        if text == "/cost":
            console.print("  " + bridge.agent.usage.summary(bridge.agent.cost_model))
            continue
        with bridge._lock:
            try:
                bridge.agent.run_turn(text)
            except Exception as e:  # noqa: BLE001
                console.print(f"[#F87171]error:[/] {type(e).__name__}: {e}")


def build_agent(args: argparse.Namespace) -> Agent:
    ensure_dirs()
    cfg = Config.load()
    if args.ollama_host:
        cfg.ollama_host = args.ollama_host
    if args.openai_base_url:
        cfg.openai_base_url = args.openai_base_url
    if args.no_learning:
        cfg.learning = False
    if args.no_web:
        cfg.enable_web = False
    if args.browser_window:
        cfg.browser_headless = False
    if args.auto:
        cfg.auto = True
    if args.yolo:
        cfg.yolo = True
    if args.no_thinking:
        cfg.thinking = False
    if args.effort:
        cfg.effort = args.effort

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

    console = Console(record=True, force_terminal=False, width=100)
    factory = _setup_backend(cfg, console)
    if factory is None:
        raise RuntimeError(console.export_text())
    return Agent(factory, cfg, console)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"\''))


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="zuse-telegram",
        description="Run Zuse as a Telegram bot via the Telegram Bot API",
    )
    p.add_argument("-m", "--model")
    p.add_argument("--local", action="store_true", help="Use a local model via Ollama")
    p.add_argument("--provider", choices=["anthropic", "ollama", "openai", "codex"])
    p.add_argument("--ollama-host")
    p.add_argument("--openai-base-url")
    p.add_argument("-e", "--effort", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--auto", action="store_true", default=True, help="Autonomous mode for Telegram tasks (default)")
    p.add_argument("--no-auto", action="store_false", dest="auto")
    p.add_argument("--yolo", action="store_true", help="Auto-approve all tool permissions")
    p.add_argument("--no-thinking", action="store_true")
    p.add_argument("--no-web", action="store_true")
    p.add_argument("--no-learning", action="store_true")
    p.add_argument("--browser-window", action="store_true")
    p.add_argument(
        "--allowed-chat-id",
        action="append",
        type=int,
        default=[],
        help="Only allow this Telegram chat ID. Can be repeated. Also supports ZUSE_TELEGRAM_ALLOWED_CHAT_IDS.",
    )
    p.add_argument(
        "--no-local-input",
        action="store_true",
        help="Do not open a local terminal input loop for the shared session",
    )
    p.add_argument("--env-file", type=Path, help="Optional .env file with TELEGRAM_BOT_TOKEN")
    return p


def run_polling(args: argparse.Namespace) -> int:
    console = ui.make_console()
    console.print(
        Panel.fit(
            "[bold]Zuse Telegram-Bot[/]\n\n"
            "Erstelle in Telegram mit [bold]@BotFather[/] einen Bot, setze "
            "[bold]TELEGRAM_BOT_TOKEN[/] und schreibe dem Bot eine Nachricht.\n\n"
            "Optional kannst du nach der ersten Nachricht die angezeigte Chat-ID als Allowlist setzen.",
            border_style="#22d3ee",
        )
    )

    settings = TelegramSettings.from_env()
    settings.validate()
    if args.allowed_chat_id:
        settings = TelegramSettings(
            bot_token=settings.bot_token,
            allowed_chat_ids=tuple(args.allowed_chat_id),
            api_base=settings.api_base,
        )
    client = TelegramClient(settings)
    me = client.get_me().get("result", {})
    username = me.get("username") or me.get("first_name") or "unbekannt"

    console.print("Initialisiere eine persistente Zuse-Session für Telegram und lokale Eingriffe ...")
    bridge = ZuseTelegramBridge(build_agent(args), client, settings)
    stop = threading.Event()
    errors = 0

    def poll_loop() -> None:
        nonlocal errors
        offset: int | None = None
        console.print(f"[#34D399]Zuse Telegram läuft[/] als @{username}. Schreibe dem Bot jetzt eine Nachricht.")
        while not stop.is_set():
            try:
                updates = client.get_updates(offset=offset, timeout=30)
                errors = 0
                for update in updates:
                    update_id = int(update.get("update_id", 0))
                    offset = update_id + 1
                    msg = extract_text_message(update)
                    if msg is None:
                        continue
                    if not settings.allowed_chat_ids:
                        console.print(f"Telegram Nachricht von Chat-ID [bold]{msg.chat_id}[/] ({msg.username})")
                    threading.Thread(target=bridge.handle, args=(msg,), daemon=True).start()
            except Exception as e:  # noqa: BLE001
                errors += 1
                console.print(f"[#F87171]Telegram polling error:[/] {type(e).__name__}: {e}")
                time.sleep(min(30, 2 * errors))

    thread = threading.Thread(target=poll_loop, daemon=True)
    thread.start()
    try:
        if args.no_local_input:
            while thread.is_alive():
                time.sleep(0.5)
        else:
            run_terminal_control_loop(bridge, console)
        return 0
    except KeyboardInterrupt:
        console.print("\n[#FBBF24]Telegram-Bridge beendet.[/]")
        return 130
    finally:
        stop.set()
        bridge.agent.shutdown()


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.env_file:
        _load_env_file(args.env_file)
    try:
        return run_polling(args)
    except Exception as e:  # noqa: BLE001
        print(f"Cannot start Telegram bridge: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
