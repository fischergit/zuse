"""WhatsApp Cloud API bridge for Zuse.

This module exposes a small FastAPI app that receives Meta WhatsApp webhook
messages, runs them through a long-lived Zuse Agent, and sends the answer back
through the WhatsApp Cloud API.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import time
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from .agent import Agent
from .cli import _decide_provider, _setup_backend
from .config import CONFIG_DIR, Config, ensure_dirs, resolve_model
from . import ui

if TYPE_CHECKING:
    from fastapi import Request as FastAPIRequest


@dataclass(frozen=True)
class IncomingMessage:
    """A normalized incoming WhatsApp text message."""

    message_id: str
    sender: str
    text: str


@dataclass(frozen=True)
class WhatsAppSettings:
    """Settings for Meta WhatsApp Cloud API."""

    verify_token: str
    access_token: str
    phone_number_id: str
    app_secret: str = ""
    allowed_senders: tuple[str, ...] = ()
    api_version: str = "v20.0"

    @classmethod
    def from_env(cls) -> "WhatsAppSettings":
        allowed = tuple(
            normalize_phone(s)
            for s in os.environ.get("ZUSE_WHATSAPP_ALLOWED_SENDERS", "").split(",")
            if s.strip()
        )
        return cls(
            verify_token=os.environ.get("ZUSE_WHATSAPP_VERIFY_TOKEN", ""),
            access_token=os.environ.get("WHATSAPP_ACCESS_TOKEN", ""),
            phone_number_id=os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
            app_secret=os.environ.get("WHATSAPP_APP_SECRET", ""),
            allowed_senders=allowed,
            api_version=os.environ.get("WHATSAPP_API_VERSION", "v20.0"),
        )

    def validate(self) -> None:
        missing = []
        if not self.verify_token:
            missing.append("ZUSE_WHATSAPP_VERIFY_TOKEN")
        if not self.access_token:
            missing.append("WHATSAPP_ACCESS_TOKEN")
        if not self.phone_number_id:
            missing.append("WHATSAPP_PHONE_NUMBER_ID")
        if missing:
            raise RuntimeError("Missing environment variable(s): " + ", ".join(missing))


def normalize_phone(value: str) -> str:
    """Keep only digits so +49... and 49... compare equal."""

    return re.sub(r"\D+", "", value)


def extract_text_messages(payload: dict[str, Any]) -> list[IncomingMessage]:
    """Extract text messages from a Meta WhatsApp webhook payload.

    Non-text messages and status callbacks are ignored.
    """

    out: list[IncomingMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []) or []:
                if msg.get("type") != "text":
                    continue
                text = (msg.get("text") or {}).get("body", "").strip()
                sender = normalize_phone(str(msg.get("from", "")))
                message_id = str(msg.get("id", ""))
                if text and sender and message_id:
                    out.append(IncomingMessage(message_id=message_id, sender=sender, text=text))
    return out


def verify_meta_signature(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Validate X-Hub-Signature-256 when WHATSAPP_APP_SECRET is configured."""

    if not app_secret:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


class WhatsAppClient:
    def __init__(self, settings: WhatsAppSettings) -> None:
        self.settings = settings

    def send_text(self, to: str, body: str) -> None:
        """Send a WhatsApp text message, chunking long answers."""

        for chunk in _chunks(body.strip() or "(keine Antwort)", 3900):
            self._post(
                {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": to,
                    "type": "text",
                    "text": {"preview_url": False, "body": chunk},
                }
            )

    def mark_read(self, message_id: str) -> None:
        self._post(
            {
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": message_id,
            }
        )

    def _post(self, payload: dict[str, Any]) -> None:
        url = (
            f"https://graph.facebook.com/{self.settings.api_version}/"
            f"{self.settings.phone_number_id}/messages"
        )
        req = Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self.settings.access_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed Meta API URL
                resp.read()
        except HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise RuntimeError(f"WhatsApp API error {e.code}: {detail}") from e
        except URLError as e:
            raise RuntimeError(f"WhatsApp API request failed: {e}") from e


def _chunks(text: str, limit: int) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)] or [""]


# -- OpenClaw-style QR bridge via WhatsApp Web ------------------------------

WWEBJS_BRIDGE_DIR = CONFIG_DIR / "whatsapp-web-bridge"
WWEBJS_PACKAGE_JSON = """{
  "name": "zuse-whatsapp-web-bridge",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "dependencies": {
    "@wppconnect-team/wppconnect": "^1.37.5"
  }
}
"""
WWEBJS_RUNNER = r"""
import wppconnect from '@wppconnect-team/wppconnect';
import http from 'node:http';

const port = Number(process.env.ZUSE_WHATSAPP_QR_PORT || '8797');
const zuseReplyMarker = '\u2063\u200b\u2063';

function asSerializedId(value) {
  if (!value) return '';
  if (typeof value === 'string') return value;
  if (value._serialized) return value._serialized;
  if (value.user && value.server) return `${value.user}@${value.server}`;
  return String(value);
}

function isOwnSelfChatMessage(message) {
  if (!message.fromMe) return false;
  const from = asSerializedId(message.from);
  const to = asSerializedId(message.to);
  const chatId = asSerializedId(message.chatId);
  return Boolean(from && to && from === to && (!chatId || chatId === from));
}

function messageId(message) {
  return asSerializedId(message.id) || message.id?._serialized || `${Date.now()}`;
}

function replyTarget(message) {
  return asSerializedId(message.chatId) || asSerializedId(message.from) || asSerializedId(message.to);
}

function logicalSender(message) {
  return asSerializedId(message.from) || asSerializedId(message.to) || replyTarget(message);
}

function postJson(path, payload) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(payload);
    const req = http.request({
      hostname: '127.0.0.1',
      port,
      path,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(data),
      },
    }, (res) => {
      let body = '';
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(new Error(`HTTP ${res.statusCode}: ${body}`));
          return;
        }
        try { resolve(JSON.parse(body || '{}')); } catch { resolve({}); }
      });
    });
    req.on('error', reject);
    req.write(data);
    req.end();
  });
}

wppconnect.create({
  session: 'zuse',
  catchQR: (base64Qrimg, asciiQR, attempts, urlCode) => {
    console.log('\nScanne diesen QR-Code in WhatsApp: Menü/Einstellungen → Verknüpfte Geräte → Gerät verknüpfen\n');
    console.log(asciiQR || urlCode || base64Qrimg);
    console.log('\nWarte auf WhatsApp-Verbindung...\n');
  },
  statusFind: (statusSession) => console.log(`WhatsApp status: ${statusSession}`),
  headless: 'new',
  logQR: true,
}).then((client) => {
  console.log('✅ Zuse ist mit WhatsApp verbunden. Schreibe dem verknüpften Account eine Nachricht.');
  console.log('   Tipp ohne zweite Nummer: Schreibe dir selbst; Zuse reagiert im Selbst-Chat.');
  client.onAnyMessage(async (message) => {
    const body = (message.body || '').trim();
    if (!body || message.isGroupMsg || body.includes(zuseReplyMarker)) return;
    if (message.fromMe && !isOwnSelfChatMessage(message)) return;
    const target = replyTarget(message);
    if (!target) return;
    try {
      const result = await postJson('/message', {
        id: messageId(message),
        from: logicalSender(message),
        body,
      });
      if (result.reply) await client.sendText(target, `${zuseReplyMarker}${result.reply}`);
    } catch (e) {
      await client.sendText(target, `${zuseReplyMarker}Fehler in Zuse: ${e.message}`);
    }
  });
}).catch((e) => {
  console.error('WhatsApp-Web-Bridge konnte nicht starten:', e);
  process.exit(1);
});
""".strip() + "\n"


def ensure_web_bridge_files(base: Path = WWEBJS_BRIDGE_DIR) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / "package.json").write_text(WWEBJS_PACKAGE_JSON)
    (base / "zuse-whatsapp-web.mjs").write_text(WWEBJS_RUNNER)


def node_available() -> bool:
    return shutil.which("node") is not None and shutil.which("npm") is not None


class WhatsAppWebSession:
    """A persistent in-process Zuse session shared by WhatsApp Web and this terminal."""

    def __init__(self, agent: Agent, allowed_sender: str = "") -> None:
        self.agent = agent
        self.allowed_sender = normalize_phone(allowed_sender)
        self._lock = threading.Lock()
        self._seen: set[str] = set()

    def handle_message(self, message_id: str, sender: str, body: str) -> str:
        normalized_sender = normalize_phone(sender)
        if message_id in self._seen:
            return ""
        self._seen.add(message_id)
        if self.allowed_sender and normalized_sender != self.allowed_sender:
            return "Diese Nummer ist für Zuse nicht freigeschaltet."
        if not self._lock.acquire(blocking=False):
            return "Zuse arbeitet gerade noch an der vorherigen Anfrage."
        try:
            return self.agent.run_turn(body) or "Fertig."
        except Exception as e:  # noqa: BLE001
            return f"Fehler in Zuse: {type(e).__name__}: {e}"
        finally:
            self._lock.release()


def run_terminal_control_loop(session: WhatsAppWebSession, console: Console) -> None:
    """Let the user inject turns into the same WhatsApp-backed agent session."""

    console.print(
        "[#22d3ee]Lokale Eingriffe sind aktiv.[/] Tippe hier Nachrichten in dieselbe "
        "Zuse-Session. Befehle: [bold]/quit[/], [bold]/clear[/], [bold]/cost[/]."
    )
    while True:
        try:
            text = Prompt.ask("[bold #22d3ee]lokal ❯[/]", default="", console=console).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[#FBBF24]Lokale Eingabe beendet; WhatsApp läuft weiter bis Ctrl+C.[/]")
            return
        if not text:
            continue
        if text in {"/quit", "/exit", "/q"}:
            raise KeyboardInterrupt
        if text == "/clear":
            session.agent.backend.clear()
            session.agent.permissions.reset_session()
            console.print("[green]Conversation cleared.[/]")
            continue
        if text == "/cost":
            console.print("  " + session.agent.usage.summary(session.agent.cost_model))
            continue
        with session._lock:
            try:
                session.agent.run_turn(text)
            except Exception as e:  # noqa: BLE001
                console.print(f"[#F87171]error:[/] {type(e).__name__}: {e}")


def start_qr_http_server(session: WhatsAppWebSession, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib API
            if self.path != "/message":
                self.send_error(404)
                return
            length = int(self.headers.get("content-length", "0"))
            try:
                payload = json.loads(self.rfile.read(length).decode() or "{}")
                reply = session.handle_message(
                    str(payload.get("id", "")), str(payload.get("from", "")), str(payload.get("body", ""))
                )
                data = json.dumps({"reply": reply}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:  # noqa: BLE001
                data = json.dumps({"reply": f"Fehler in Zuse: {type(e).__name__}: {e}"}).encode()
                self.send_response(500)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run_web_qr_assistant(args: argparse.Namespace) -> int:
    """Start a WhatsApp-Web pairing assistant that shows a QR code in the terminal."""

    console = ui.make_console()
    console.print(
        Panel.fit(
            "[bold]Zuse WhatsApp QR-Einrichtung[/]\n\n"
            "Das ist der OpenClaw-ähnliche Modus: WhatsApp auf dem Handy öffnen, "
            "[bold]Verknüpfte Geräte[/] wählen und den QR-Code scannen.\n\n"
            "Hinweis: Diese Variante nutzt WhatsApp Web über WPPConnect, nicht die offizielle "
            "Meta Cloud API. Sie ist bequem, aber inoffiziell.",
            border_style="#22d3ee",
        )
    )
    if not node_available():
        console.print("[#F87171]Node.js und npm werden benötigt.[/] Installiere Node.js und starte erneut.")
        return 1

    allowed_sender = args.allowed_sender or os.environ.get("ZUSE_WHATSAPP_ALLOWED_SENDERS", "")
    if not allowed_sender:
        allowed_sender = Prompt.ask(
            "Deine WhatsApp-Nummer als Allowlist, z. B. 491701234567 (leer = alle erlauben)",
            default="",
            console=console,
        ).strip()

    ensure_web_bridge_files()
    if not (WWEBJS_BRIDGE_DIR / "node_modules").exists():
        console.print("Installiere WhatsApp-Web-Abhängigkeiten in ~/.zuse/whatsapp-web-bridge ...")
        subprocess.run(["npm", "install"], cwd=WWEBJS_BRIDGE_DIR, check=True)

    console.print("Initialisiere eine persistente Zuse-Session für WhatsApp und lokale Eingriffe ...")
    session = WhatsAppWebSession(build_agent(args), allowed_sender)
    server = start_qr_http_server(session, args.qr_port)
    env = os.environ.copy()
    env["ZUSE_WHATSAPP_QR_PORT"] = str(args.qr_port)

    console.print(
        "Starte WhatsApp-Web-Bridge. Der QR-Code erscheint gleich im Terminal. "
        "Danach kannst du parallel hier lokal in dieselbe Session eingreifen."
    )
    if not Confirm.ask("Fortfahren?", default=True, console=console):
        server.shutdown()
        session.agent.shutdown()
        return 0

    proc = subprocess.Popen(["node", "zuse-whatsapp-web.mjs"], cwd=WWEBJS_BRIDGE_DIR, env=env)
    try:
        if args.no_local_input:
            while proc.poll() is None:
                time.sleep(0.5)
            return proc.returncode or 0
        run_terminal_control_loop(session, console)
        return 0
    except KeyboardInterrupt:
        console.print("\n[#FBBF24]WhatsApp-Bridge beendet.[/]")
        return 130
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        server.shutdown()
        session.agent.shutdown()


class ZuseWhatsAppBridge:
    """Thread-safe wrapper around one Zuse Agent conversation."""

    def __init__(self, agent: Agent, client: WhatsAppClient, settings: WhatsAppSettings) -> None:
        self.agent = agent
        self.client = client
        self.settings = settings
        self._lock = threading.Lock()
        self._seen: set[str] = set()

    def allowed(self, sender: str) -> bool:
        if not self.settings.allowed_senders:
            return True
        return normalize_phone(sender) in {normalize_phone(s) for s in self.settings.allowed_senders}

    def handle(self, msg: IncomingMessage) -> None:
        if msg.message_id in self._seen:
            return
        self._seen.add(msg.message_id)
        if not self.allowed(msg.sender):
            self.client.send_text(msg.sender, "Diese Nummer ist für Zuse nicht freigeschaltet.")
            return

        self.client.mark_read(msg.message_id)
        with self._lock:
            try:
                answer = self.agent.run_turn(msg.text) or "Fertig."
            except Exception as e:  # noqa: BLE001
                answer = f"Fehler in Zuse: {type(e).__name__}: {e}"
        self.client.send_text(msg.sender, answer)


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


def create_app(agent_factory: Callable[[], Agent] | None = None):
    """Create the FastAPI app. Kept import-lazy so normal Zuse installs need no FastAPI."""

    try:
        from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
        from fastapi.responses import PlainTextResponse
    except ImportError as e:  # pragma: no cover - exercised by import checks only
        raise RuntimeError('Install with: pip install -e ".[whatsapp]"') from e

    settings = WhatsAppSettings.from_env()
    settings.validate()
    agent = agent_factory() if agent_factory else build_agent(_default_args())
    bridge = ZuseWhatsAppBridge(agent, WhatsAppClient(settings), settings)
    app = FastAPI(title="Zuse WhatsApp Bridge")

    @app.get("/webhook/whatsapp", response_class=PlainTextResponse)
    def verify(
        hub_mode: str = Query("", alias="hub.mode"),
        hub_verify_token: str = Query("", alias="hub.verify_token"),
        hub_challenge: str = Query("", alias="hub.challenge"),
    ) -> str:
        if hub_mode == "subscribe" and hub_verify_token == settings.verify_token:
            return hub_challenge
        raise HTTPException(status_code=403, detail="verification failed")

    @app.post("/webhook/whatsapp")
    async def webhook(request: "FastAPIRequest", background: BackgroundTasks) -> dict[str, str]:
        raw = await request.body()
        if not verify_meta_signature(
            raw, request.headers.get("x-hub-signature-256"), settings.app_secret
        ):
            raise HTTPException(status_code=403, detail="invalid signature")
        payload = json.loads(raw.decode() or "{}")
        for msg in extract_text_messages(payload):
            background.add_task(bridge.handle, msg)
        return {"status": "ok"}

    return app


def _default_args() -> argparse.Namespace:
    return argparse.Namespace(
        provider=None,
        local=False,
        model=None,
        ollama_host=None,
        openai_base_url=None,
        no_learning=False,
        no_web=False,
        browser_window=False,
        auto=True,
        yolo=False,
        no_thinking=False,
        effort=None,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="zuse-whatsapp",
        description="Run Zuse via WhatsApp: QR pairing assistant or Meta Cloud API webhook",
    )
    p.add_argument(
        "--mode",
        choices=["qr", "cloud"],
        default=os.environ.get("ZUSE_WHATSAPP_MODE", "qr"),
        help="qr = WhatsApp-Web QR pairing assistant (default), cloud = Meta Cloud API webhook",
    )
    p.add_argument("--host", default=os.environ.get("ZUSE_WHATSAPP_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("ZUSE_WHATSAPP_PORT", "8787")))
    p.add_argument(
        "--qr-port",
        type=int,
        default=int(os.environ.get("ZUSE_WHATSAPP_QR_PORT", "8797")),
        help="Local HTTP port used internally between the QR runner and Zuse",
    )
    p.add_argument("-m", "--model")
    p.add_argument("--local", action="store_true", help="Use a local model via Ollama")
    p.add_argument("--provider", choices=["anthropic", "ollama", "openai", "codex"])
    p.add_argument("--ollama-host")
    p.add_argument("--openai-base-url")
    p.add_argument("-e", "--effort", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument(
        "--auto", action="store_true", default=True, help="Autonomous mode for WhatsApp tasks (default)"
    )
    p.add_argument("--no-auto", action="store_false", dest="auto")
    p.add_argument("--yolo", action="store_true", help="Auto-approve all tool permissions")
    p.add_argument("--no-thinking", action="store_true")
    p.add_argument("--no-web", action="store_true")
    p.add_argument("--no-learning", action="store_true")
    p.add_argument("--browser-window", action="store_true")
    p.add_argument(
        "--allowed-sender",
        help="Only allow this WhatsApp sender number in QR mode, e.g. 491701234567",
    )
    p.add_argument(
        "--no-local-input",
        action="store_true",
        help="QR mode: do not open a local terminal input loop for the shared session",
    )
    p.add_argument("--env-file", type=Path, help="Optional .env file with WhatsApp tokens")
    return p


def _load_env_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"\''))


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.env_file:
        _load_env_file(args.env_file)

    if args.mode == "qr":
        return run_web_qr_assistant(args)

    try:
        import uvicorn
    except ImportError:
        print('Install WhatsApp extras first: pip install -e ".[whatsapp]"')
        return 1

    def factory() -> Agent:
        return build_agent(args)

    try:
        app = create_app(factory)
    except Exception as e:  # noqa: BLE001
        print(f"Cannot start WhatsApp bridge: {e}")
        return 1

    ui.make_console().print(
        f"[#34D399]Zuse WhatsApp bridge listening[/] on http://{args.host}:{args.port}/webhook/whatsapp"
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
