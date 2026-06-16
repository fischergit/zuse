"""Small local graphical interface for Zuse.

The GUI is intentionally dependency-free and uses Tkinter from the Python
standard library. It keeps one persistent Zuse Agent in the process and runs each
turn in a worker thread so the window stays responsive.
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rich.console import Console

from . import __version__
from .agent import Agent
from .cli import _decide_provider, _setup_backend
from .config import CONFIG_DIR, Config, ensure_dirs, resolve_model
from .session import save_session


@dataclass(frozen=True)
class GuiEvent:
    kind: str
    text: str = ""


class QueueWriter:
    """File-like writer that forwards Rich console output to the GUI queue."""

    def __init__(self, events: "queue.Queue[GuiEvent]", prefix: str = "") -> None:
        self.events = events
        self.prefix = prefix
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self.events.put(GuiEvent("log", self.prefix + line.rstrip()))
        return len(text)

    def flush(self) -> None:
        if self._buffer.strip():
            self.events.put(GuiEvent("log", self.prefix + self._buffer.rstrip()))
        self._buffer = ""

    def isatty(self) -> bool:
        return False


def build_agent(args: argparse.Namespace, events: "queue.Queue[GuiEvent]") -> Agent:
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
    if args.no_markdown:
        cfg.stream_markdown = False
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

    console = Console(
        file=QueueWriter(events),
        force_terminal=False,
        color_system=None,
        width=100,
        record=True,
    )
    factory = _setup_backend(cfg, console)
    if factory is None:
        raise RuntimeError(console.export_text() or "Backend konnte nicht initialisiert werden.")
    return Agent(factory, cfg, console)


class ZuseGui:
    def __init__(self, root, args: argparse.Namespace) -> None:
        import tkinter as tk
        from tkinter import scrolledtext, ttk

        self.root = root
        self.args = args
        self.events: queue.Queue[GuiEvent] = queue.Queue()
        self.agent: Agent | None = None
        self.busy = False
        self._tk = tk

        root.title("Zuse")
        root.geometry("980x720")
        root.minsize(720, 520)

        self.status = tk.StringVar(value="Initialisiere Zuse …")
        self.input_var = tk.StringVar()

        outer = ttk.Frame(root, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(outer)
        header.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(header, text="Zuse", font=("Helvetica", 22, "bold")).pack(side=tk.LEFT)
        ttk.Label(header, textvariable=self.status).pack(side=tk.RIGHT)

        self.chat = scrolledtext.ScrolledText(
            outer,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("Menlo", 13),
            padx=10,
            pady=10,
        )
        self.chat.pack(fill=tk.BOTH, expand=True)
        self.chat.tag_configure("user", foreground="#0284c7", font=("Menlo", 13, "bold"))
        self.chat.tag_configure("assistant", foreground="#16a34a", font=("Menlo", 13, "bold"))
        self.chat.tag_configure("system", foreground="#a16207")
        self.chat.tag_configure("error", foreground="#dc2626")
        self.chat.tag_configure("log", foreground="#6b7280")

        controls = ttk.Frame(outer)
        controls.pack(fill=tk.X, pady=(8, 0))
        self.entry = ttk.Entry(controls, textvariable=self.input_var)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry.bind("<Return>", lambda _event: self.send())
        self.entry.bind("<Shift-Return>", lambda _event: self.send())

        self.send_button = ttk.Button(controls, text="Senden", command=self.send)
        self.send_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(controls, text="Clear", command=self.clear_conversation).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(controls, text="Kosten", command=self.show_cost).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(controls, text="Speichern", command=self.save_conversation).pack(side=tk.LEFT, padx=(8, 0))

        self.append("system", "Zuse GUI startet. Du kannst gleich eine Aufgabe eingeben.\n")
        self.entry.focus_set()
        threading.Thread(target=self._init_agent, daemon=True).start()
        self.root.after(80, self.process_events)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def append(self, tag: str, text: str) -> None:
        self.chat.configure(state=self._tk.NORMAL)
        if tag == "user":
            self.chat.insert(self._tk.END, "\nDu:\n", ("user",))
        elif tag == "assistant":
            self.chat.insert(self._tk.END, "\nZuse:\n", ("assistant",))
        elif tag == "system":
            self.chat.insert(self._tk.END, "\nSystem:\n", ("system",))
        elif tag == "error":
            self.chat.insert(self._tk.END, "\nFehler:\n", ("error",))
        self.chat.insert(self._tk.END, text.rstrip() + "\n", (tag,))
        self.chat.see(self._tk.END)
        self.chat.configure(state=self._tk.DISABLED)

    def _init_agent(self) -> None:
        try:
            self.agent = build_agent(self.args, self.events)
            cfg = self.agent.config
            self.events.put(GuiEvent("ready", f"Bereit — {cfg.provider} / {cfg.active_model}"))
        except Exception as e:  # noqa: BLE001
            self.events.put(GuiEvent("error", f"Start fehlgeschlagen: {type(e).__name__}: {e}"))

    def process_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event.kind == "ready":
                    self.status.set(event.text)
                    self.append("system", event.text)
                    self.set_busy(False)
                elif event.kind == "user":
                    self.append("user", event.text)
                elif event.kind == "assistant":
                    self.append("assistant", event.text or "Fertig.")
                    self.set_busy(False)
                elif event.kind == "log":
                    self.append("log", event.text)
                elif event.kind == "status":
                    self.status.set(event.text)
                elif event.kind == "error":
                    self.append("error", event.text)
                    self.status.set("Fehler")
                    self.set_busy(False)
        except queue.Empty:
            pass
        self.root.after(80, self.process_events)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = self._tk.DISABLED if busy or self.agent is None else self._tk.NORMAL
        self.send_button.configure(state=state)
        self.entry.configure(state=state)
        if not busy and self.agent is not None:
            self.entry.focus_set()

    def send(self) -> None:
        text = self.input_var.get().strip()
        if not text or self.busy or self.agent is None:
            return
        if text in {"/quit", "/exit", "/q"}:
            self.close()
            return
        self.input_var.set("")
        self.set_busy(True)
        self.status.set("Zuse arbeitet …")
        self.events.put(GuiEvent("user", text))
        threading.Thread(target=self._run_turn, args=(text,), daemon=True).start()

    def _run_turn(self, text: str) -> None:
        assert self.agent is not None
        started = time.time()
        try:
            answer = self.agent.run_turn(text) or "Fertig."
            elapsed = time.time() - started
            self.events.put(GuiEvent("assistant", answer))
            self.events.put(GuiEvent("status", f"Bereit — letzte Antwort {elapsed:.1f}s"))
        except Exception as e:  # noqa: BLE001
            self.events.put(GuiEvent("error", f"{type(e).__name__}: {e}"))

    def clear_conversation(self) -> None:
        if self.agent is None or self.busy:
            return
        self.agent.backend.clear()
        self.agent.permissions.reset_session()
        self.append("system", "Conversation cleared.")

    def show_cost(self) -> None:
        if self.agent is None:
            return
        self.append("system", self.agent.usage.summary(self.agent.cost_model))

    def save_conversation(self) -> None:
        if self.agent is None:
            return
        name = f"gui-{time.strftime('%Y%m%d-%H%M%S')}"
        save_session(name, self.agent.backend.export_messages())
        self.append("system", f"Gespeichert als {name} in {CONFIG_DIR / 'sessions' / (name + '.json')}")

    def close(self) -> None:
        if self.agent is not None:
            try:
                self.agent.shutdown()
            except Exception:  # noqa: BLE001
                pass
        self.root.destroy()


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="zuse-gui", description="Zuse — lokale grafische Oberfläche")
    p.add_argument("-m", "--model")
    p.add_argument("--local", action="store_true", help="Use a local model via Ollama")
    p.add_argument("--provider", choices=["anthropic", "ollama", "openai", "codex"])
    p.add_argument("--ollama-host")
    p.add_argument("--openai-base-url")
    p.add_argument("-e", "--effort", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--auto", action="store_true", default=True, help="Autonomous mode (default)")
    p.add_argument("--no-auto", action="store_false", dest="auto")
    p.add_argument("--yolo", action="store_true", help="Auto-approve all tool permissions")
    p.add_argument("--no-thinking", action="store_true")
    p.add_argument("--no-web", action="store_true")
    p.add_argument("--no-learning", action="store_true")
    p.add_argument("--no-markdown", action="store_true")
    p.add_argument("--browser-window", action="store_true")
    p.add_argument("-v", "--version", action="version", version=f"zuse-gui {__version__}")
    return p


def run_gui(args: argparse.Namespace) -> int:
    try:
        import tkinter as tk
    except ImportError:
        print("Tkinter ist nicht installiert. Nutze auf macOS die python.org/Homebrew-Python-Variante mit Tk-Support.")
        return 1

    root = tk.Tk()
    ZuseGui(root, args)
    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    return run_gui(args)


if __name__ == "__main__":
    sys.exit(main())
