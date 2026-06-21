"""Live registry of running sub-agents.

A crew spawns several specialist sub-agents that run in parallel threads. Each
one reports its progress (status, step count, current activity) into a shared
``AgentRegistry`` so the terminal dashboard can show — live — which agents are
working and how far along they are. One registry is created per crew run; it is
not global state.
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, replace

# Lifecycle states for a single sub-agent run.
QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"


@dataclass
class AgentRun:
    """A single sub-agent's live state. Mutated only via :class:`AgentRegistry`
    (under its lock); :meth:`AgentRegistry.snapshot` hands out copies."""

    id: str
    role: str
    title: str
    status: str = QUEUED
    step: int = 0
    max_steps: int = 0
    todos_done: int = 0
    todos_total: int = 0
    activity: str = ""
    error: str = ""
    started: float = 0.0
    ended: float = 0.0

    @property
    def elapsed(self) -> float:
        """Seconds running so far (or total, once finished)."""
        if not self.started:
            return 0.0
        return (self.ended or time.monotonic()) - self.started

    @property
    def fraction(self) -> float:
        """Best-effort progress in [0, 1].

        Uses the agent's own todo plan when it made one (the most honest signal),
        otherwise falls back to step count against its ``max_steps`` ceiling.
        Finished agents always read as full.
        """
        if self.status in (DONE, FAILED):
            return 1.0
        if self.todos_total > 0:
            return min(1.0, self.todos_done / self.todos_total)
        if self.max_steps > 0:
            return min(1.0, self.step / self.max_steps)
        return 0.0


class AgentRegistry:
    """Thread-safe collection of :class:`AgentRun`s, preserving creation order."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, AgentRun] = {}
        self._order: list[str] = []
        self._ids = itertools.count(1)

    def create(self, role: str, title: str, max_steps: int) -> str:
        """Register a queued agent and return its id."""
        with self._lock:
            rid = f"a{next(self._ids)}"
            self._runs[rid] = AgentRun(id=rid, role=role, title=title, max_steps=max_steps)
            self._order.append(rid)
            return rid

    def update(self, rid: str, **fields) -> None:
        """Set arbitrary fields on a run (no-op if the id is unknown)."""
        with self._lock:
            run = self._runs.get(rid)
            if run is not None:
                for key, value in fields.items():
                    setattr(run, key, value)

    def start(self, rid: str) -> None:
        self.update(rid, status=RUNNING, started=time.monotonic())

    def finish(self, rid: str, ok: bool = True, error: str = "") -> None:
        self.update(
            rid,
            status=DONE if ok else FAILED,
            error=error,
            ended=time.monotonic(),
        )

    def snapshot(self) -> list[AgentRun]:
        """Immutable copies of every run, in creation order."""
        with self._lock:
            return [replace(self._runs[rid]) for rid in self._order]
