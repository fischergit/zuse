"""Persistent shell session and background-process manager.

The persistent shell keeps state (working directory, environment, shell
variables, venv activation) across tool calls — unlike one-shot subprocess
runs. Background processes (dev servers, watchers) run detached with their
output captured to log files the agent can read later.
"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
import uuid
from pathlib import Path


class ShellSession:
    """A long-lived /bin/bash process driven over pipes. Commands run in order
    and share state. On timeout the session is reset so it never wedges."""

    def __init__(self, cwd: Path) -> None:
        self.cwd = str(cwd)
        self.proc: subprocess.Popen | None = None
        self._q: queue.Queue[str] = queue.Queue()
        self._start()

    def _start(self) -> None:
        self.proc = subprocess.Popen(
            ["/bin/bash", "--norc"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=self.cwd,
            env=os.environ.copy(),
        )
        self._q = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        assert self.proc and self.proc.stdout
        try:
            for line in self.proc.stdout:
                self._q.put(line)
        except (ValueError, OSError):
            pass

    def run(self, command: str, timeout: int = 120) -> tuple[str, int | None]:
        if self.proc is None or self.proc.poll() is not None:
            self._start()
        assert self.proc and self.proc.stdin
        sentinel = f"__ZUSE_{uuid.uuid4().hex}__"
        try:
            self.proc.stdin.write(command + "\n")
            self.proc.stdin.write(f'printf "\\n{sentinel}:%s\\n" "$?"\n')
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            self._start()
            return "[shell was not running; it has been reset — retry]", None

        deadline = time.monotonic() + timeout
        out: list[str] = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.kill()
                self._start()
                body = "\n".join(out)
                return (body + f"\n[timed out after {timeout}s; shell was reset. "
                        "Use run_background for long-running commands.]"), 124
            try:
                line = self._q.get(timeout=min(0.4, remaining))
            except queue.Empty:
                continue
            if sentinel in line:
                try:
                    code: int | None = int(line.strip().rsplit(":", 1)[-1])
                except ValueError:
                    code = None
                return "\n".join(out), code
            out.append(line.rstrip("\n"))

    def kill(self) -> None:
        if self.proc:
            try:
                self.proc.kill()
                # Reap it so crews (which spin up and tear down many short-lived
                # shells) don't accumulate zombie processes for the session.
                self.proc.wait(timeout=2)
            except Exception:  # noqa: BLE001
                pass


class BackgroundManager:
    """Runs detached processes with output captured to log files."""

    def __init__(self, logdir: Path) -> None:
        self.logdir = logdir
        self.logdir.mkdir(parents=True, exist_ok=True)
        self.tasks: dict[str, dict] = {}

    def start(self, command: str, cwd: str) -> str:
        task_id = "bg_" + uuid.uuid4().hex[:6]
        logpath = self.logdir / f"{task_id}.log"
        logf = open(logpath, "wb")
        proc = subprocess.Popen(
            command, shell=True, cwd=cwd,
            stdout=logf, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        self.tasks[task_id] = {"proc": proc, "log": logpath, "cmd": command, "logf": logf}
        return task_id

    def logs(self, task_id: str, lines: int = 40) -> str:
        t = self.tasks.get(task_id)
        if not t:
            raise KeyError(task_id)
        try:
            text = t["log"].read_text(errors="replace")
        except OSError:
            return "(no output yet)"
        tail = text.splitlines()[-lines:]
        return "\n".join(tail) if tail else "(no output yet)"

    def status(self, task_id: str) -> str:
        t = self.tasks.get(task_id)
        if not t:
            raise KeyError(task_id)
        rc = t["proc"].poll()
        return "running" if rc is None else f"exited ({rc})"

    def stop(self, task_id: str) -> str:
        t = self.tasks.get(task_id)
        if not t:
            raise KeyError(task_id)
        t["proc"].terminate()
        try:
            t["proc"].wait(timeout=5)
        except subprocess.TimeoutExpired:
            t["proc"].kill()
        return "stopped"

    def list(self) -> list[tuple[str, str, str]]:
        rows = []
        for tid, t in self.tasks.items():
            rc = t["proc"].poll()
            state = "running" if rc is None else f"exited ({rc})"
            rows.append((tid, state, t["cmd"]))
        return rows

    def shutdown(self) -> None:
        for t in self.tasks.values():
            if t["proc"].poll() is None:
                try:
                    t["proc"].terminate()
                except Exception:  # noqa: BLE001
                    pass
