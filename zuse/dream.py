"""Background "dreaming" for Zuse.

Dreaming is intentionally safe: it never runs tools and never edits project
files. It performs local memory maintenance, reflects on recent conversation
context with a separate low-effort backend call, stores durable lessons in the
KnowledgeStore, and appends improvement ideas to a user-visible backlog.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import config as config_module
from . import ui
from .config import Config
from .knowledge import KINDS, KnowledgeStore

_DREAM_SYSTEM = (
    "You are Zuse's background dreaming subsystem. You improve Zuse safely while "
    "the user is away. You may extract durable knowledge and propose improvements, "
    "but you must not claim code was changed and must not suggest destructive or "
    "secret actions. Respond with ONLY a JSON object."
)

_DREAM_INSTRUCTIONS = """
Review the context below and output ONLY JSON with this shape:
{
  "summary": "one sentence about what Zuse learned or maintained",
  "lessons": [
    {"kind": "preference|fact|procedure", "text": "durable lesson for future sessions"}
  ],
  "improvements": [
    {"priority": "low|medium|high", "title": "short backlog item", "detail": "why it would help"}
  ]
}

Rules:
- Lessons must be durable and reusable, not a transcript summary.
- Improvements are proposals only; do not imply they were implemented.
- Prefer fewer, high-signal items. Use [] when there is nothing worth saving.
""".strip()


@dataclass
class DreamResult:
    reason: str
    summary: str = ""
    learned: list[tuple[str, str]] = field(default_factory=list)
    improvements: list[dict[str, str]] = field(default_factory=list)
    maintenance: dict[str, int] = field(default_factory=dict)
    skipped: str = ""
    error: str = ""
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class DreamManager:
    def __init__(
        self,
        *,
        backend_factory: Callable[[], Any],
        config: Config,
        knowledge: KnowledgeStore,
        usage: Any = None,
        active_transcript: Callable[[], str] | None = None,
        is_idle: Callable[[], bool] | None = None,
        on_learned: Callable[[], None] | None = None,
    ) -> None:
        self.backend_factory = backend_factory
        self.config = config
        self.knowledge = knowledge
        self.usage = usage
        self.active_transcript = active_transcript or (lambda: "")
        self.is_idle = is_idle or (lambda: True)
        self.on_learned = on_learned
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._run_lock = threading.Lock()
        self.last_result: DreamResult | None = None
        self.last_started = ""
        self.last_finished = ""
        self.last_error = ""

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if not self.config.dream_enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="zuse-dream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)

    def _loop(self) -> None:
        delay = max(1, int(self.config.dream_idle_delay_seconds))
        interval = max(1, int(self.config.dream_interval_minutes)) * 60
        if self._stop.wait(delay):
            return
        while not self._stop.is_set():
            self.run_once(reason="idle")
            if self._stop.wait(interval):
                return

    # -- status -----------------------------------------------------------

    def status(self) -> dict[str, Any]:
        result = self.last_result
        return {
            "enabled": self.config.dream_enabled,
            "running": bool(self._thread and self._thread.is_alive()),
            "active": self._run_lock.locked(),
            "interval_minutes": self.config.dream_interval_minutes,
            "idle_delay_seconds": self.config.dream_idle_delay_seconds,
            "last_started": self.last_started,
            "last_finished": self.last_finished,
            "last_error": self.last_error,
            "last_summary": result.summary if result else "",
            "last_learned": len(result.learned) if result else 0,
            "last_improvements": len(result.improvements) if result else 0,
            "dreams_file": str(config_module.DREAMS_FILE),
            "improvements_file": str(config_module.IMPROVEMENTS_FILE),
        }

    # -- one cycle --------------------------------------------------------

    def run_once(self, reason: str = "manual", force: bool = False) -> DreamResult:
        if not force and not self.is_idle():
            result = DreamResult(reason=reason, skipped="agent-busy")
            self.last_result = result
            return result
        if not self._run_lock.acquire(blocking=False):
            result = DreamResult(reason=reason, skipped="already-running")
            self.last_result = result
            return result

        self.last_started = datetime.now().isoformat(timespec="seconds")
        try:
            result = self._run_once_locked(reason)
            self.last_error = result.error
            self.last_result = result
            self.last_finished = datetime.now().isoformat(timespec="seconds")
            return result
        finally:
            self._run_lock.release()

    def _run_once_locked(self, reason: str) -> DreamResult:
        result = DreamResult(reason=reason)
        try:
            compacted = self.knowledge.compact_preferences()
            deduped = self.knowledge.dedupe()
            result.maintenance = {"compacted": compacted, "deduped": deduped}

            context = self._dream_context()
            if not context.strip():
                result.summary = "Memory maintenance complete; no conversation context to dream on yet."
                self._append_dream(result)
                return result

            if not self.config.dream_model_reflection:
                result.summary = "Memory maintenance complete; model reflection is disabled."
                self._append_dream(result)
                return result

            raw = self._ask_model(context)
            parsed = parse_dream_json(raw)
            result.summary = parsed.get("summary") or "Dream cycle complete."
            result.learned = self._store_lessons(parsed.get("lessons", []))
            if result.learned and self.on_learned:
                self.on_learned()
            result.improvements = self._store_improvements(parsed.get("improvements", []))
            self._append_dream(result)
            return result
        except Exception as e:  # noqa: BLE001
            result.error = f"{type(e).__name__}: {e}"
            result.summary = "Dream cycle failed."
            self._append_dream(result)
            return result

    def _ask_model(self, context: str) -> str:
        backend = self.backend_factory()
        backend.add_user(f"{context}\n\n{_DREAM_INSTRUCTIONS}")
        response = backend.generate(_DREAM_SYSTEM, [], ui.NullView(), effort="low", think=False)
        if self.usage is not None and getattr(response, "usage", None) is not None:
            self.usage.add(response.usage)
        return response.text

    # -- context ----------------------------------------------------------

    def _dream_context(self) -> str:
        parts: list[str] = []
        transcript = self._active_transcript()
        if transcript:
            parts.append("# Current conversation\n" + transcript)
        sessions = recent_session_digest(limit=max(0, int(self.config.dream_recent_sessions)))
        if sessions:
            parts.append("# Recent saved sessions\n" + sessions)
        stats = self.knowledge.stats()
        parts.append(
            "# Current memory stats\n"
            + ", ".join(f"{key}={value}" for key, value in sorted(stats.items()))
        )
        return "\n\n".join(parts).strip()

    def _active_transcript(self) -> str:
        try:
            text = self.active_transcript().strip()
        except Exception:  # noqa: BLE001
            return ""
        return text[-12_000:]

    # -- storage ----------------------------------------------------------

    def _store_lessons(self, raw_items: Any) -> list[tuple[str, str]]:
        learned: list[tuple[str, str]] = []
        for item in raw_items if isinstance(raw_items, list) else []:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "fact")).strip()
            text = str(item.get("text", "")).strip()
            if kind not in KINDS:
                kind = "fact"
            if not text:
                continue
            entry = self.knowledge.add(kind, text)
            if entry is not None:
                learned.append((entry.kind, entry.text))
        return learned

    def _store_improvements(self, raw_items: Any) -> list[dict[str, str]]:
        items = normalize_improvements(raw_items)
        if not items:
            return []
        append_improvements(items)
        return items

    def _append_dream(self, result: DreamResult) -> None:
        path = config_module.DREAMS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")


def parse_dream_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if not raw:
        return {"summary": "", "lessons": [], "improvements": []}
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {"summary": raw[:240], "lessons": [], "improvements": []}
    try:
        data = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return {"summary": raw[:240], "lessons": [], "improvements": []}
    if not isinstance(data, dict):
        return {"summary": "", "lessons": [], "improvements": []}
    data.setdefault("summary", "")
    data.setdefault("lessons", [])
    data.setdefault("improvements", [])
    return data


def normalize_improvements(raw_items: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        detail = str(item.get("detail", "")).strip()
        priority = str(item.get("priority", "medium")).strip().lower()
        if priority not in {"low", "medium", "high"}:
            priority = "medium"
        if not title or not detail:
            continue
        key = (title.lower(), detail.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append({"priority": priority, "title": title, "detail": detail})
        if len(out) >= 8:
            break
    return out


def append_improvements(items: list[dict[str, str]]) -> None:
    path = config_module.IMPROVEMENTS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    lines: list[str] = []
    if not existing.strip():
        lines.append("# Zuse Improvement Backlog\n")
    else:
        lines.append(existing.rstrip() + "\n")
    today = datetime.now().strftime("%Y-%m-%d")
    added = 0
    for item in items:
        title = item["title"]
        detail = item["detail"]
        if title in existing and detail in existing:
            continue
        lines.append(f"- [ ] ({item['priority']}, {today}) {title} — {detail}")
        added += 1
    if added:
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def recent_session_digest(limit: int = 5, max_chars: int = 12_000) -> str:
    sessions_dir = config_module.SESSIONS_DIR
    if limit <= 0 or not sessions_dir.exists():
        return ""
    paths = sorted(sessions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    chunks: list[str] = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        name = data.get("name") or path.stem
        provider = data.get("provider") or "?"
        saved_at = data.get("saved_at") or "?"
        messages = data.get("messages") or []
        chunks.append(f"## {name} ({provider}, {saved_at})")
        for msg in messages[-8:] if isinstance(messages, list) else []:
            role = str(msg.get("role", "?")) if isinstance(msg, dict) else "?"
            content = message_content_text(msg)
            if content:
                chunks.append(f"{role}: {content[:900]}")
    text = "\n".join(chunks).strip()
    return text[-max_chars:]


def message_content_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    parts.append(str(item["text"]))
                elif item.get("content"):
                    parts.append(str(item["content"]))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts).strip()
    return str(content).strip() if content else ""
