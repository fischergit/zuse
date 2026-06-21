"""Continuous-learning knowledge store.

A growing, persistent store of things Zuse has learned: user preferences,
durable facts about the machine/projects, and reusable procedures. Entries are
recalled by relevance before each task and added passively (reflection) and
actively (the `remember` tool) as work happens. Persisted as JSONL so it
survives across sessions — this is what makes the agent improve over time.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

KINDS = ("preference", "fact", "procedure")
_TOKEN = re.compile(r"[a-zA-Z0-9_]{3,}")
_DUP_THRESHOLD = 0.82
_MAINTENANCE_DUP_THRESHOLD = 0.62
_RECALL_FLOOR = 0.06


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text)}


def _overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class Entry:
    id: str
    kind: str
    text: str
    tags: list[str] = field(default_factory=list)
    created: str = ""
    uses: int = 0
    embedding: list[float] | None = None

    def tokens(self) -> set[str]:
        return _tokens(self.text + " " + " ".join(self.tags))


class KnowledgeStore:
    def __init__(self, path: Path, embedder=None) -> None:
        self.path = path
        self.embedder = embedder
        self.entries: list[Entry] = self._load()
        # Serializes writes: parallel crew specialists may `remember` at once.
        self._lock = threading.Lock()

    # -- persistence -------------------------------------------------------

    def _load(self) -> list[Entry]:
        out: list[Entry] = []
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(Entry(**json.loads(line)))
                except (json.JSONDecodeError, TypeError):
                    continue
        return out

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("\n".join(json.dumps(asdict(e)) for e in self.entries))
        tmp.replace(self.path)

    # -- writing -----------------------------------------------------------

    def add(self, kind: str, text: str, tags: list[str] | None = None) -> Entry | None:
        text = text.strip()
        if not text:
            return None
        if kind not in KINDS:
            kind = "fact"
        new_tokens = _tokens(text)
        with self._lock:
            for e in self.entries:  # dedupe near-duplicates
                if _overlap(new_tokens, e.tokens()) >= _DUP_THRESHOLD:
                    e.uses += 1
                    self._save()
                    return None
            entry = Entry(
                id=uuid.uuid4().hex[:12],
                kind=kind,
                text=text,
                tags=tags or [],
                created=datetime.now().strftime("%Y-%m-%d"),
            )
            if self.embedder is not None:
                entry.embedding = self.embedder.embed(text)
            self.entries.append(entry)
            self._save()
        return entry

    def clear(self) -> int:
        n = len(self.entries)
        self.entries = []
        if self.path.exists():
            self.path.unlink()
        return n

    # -- maintenance -------------------------------------------------------

    def dedupe(self, threshold: float = _MAINTENANCE_DUP_THRESHOLD) -> int:
        """Merge similar learned entries and return the number removed.

        This is intentionally more aggressive than add-time dedupe because it is
        run manually when the user wants to clean up accumulated memory noise.
        The older entry is kept, use counts and tags are merged, and the shorter
        text wins when it appears to be the same information.
        """
        kept: list[Entry] = []
        removed = 0
        for entry in self.entries:
            entry_tokens = entry.tokens()
            match: Entry | None = None
            for existing in kept:
                if entry.kind != existing.kind:
                    continue
                if _overlap(entry_tokens, existing.tokens()) >= threshold:
                    match = existing
                    break
            if match is None:
                kept.append(entry)
                continue

            removed += 1
            match.uses += entry.uses + 1
            match.tags = sorted(set(match.tags) | set(entry.tags))
            if len(entry.text) < len(match.text):
                match.text = entry.text
            if not match.created or (entry.created and entry.created < match.created):
                match.created = entry.created
            if match.embedding is None and entry.embedding is not None:
                match.embedding = entry.embedding

        if removed:
            self.entries = kept
            self._save()
        return removed

    def compact_preferences(self) -> int:
        """Replace noisy preference variants with a small canonical set.

        Returns the number of preference entries removed. Facts and procedures
        are left untouched.
        """
        patterns: list[tuple[re.Pattern[str], str]] = [
            (
                re.compile(r"\b(deutsch|german|spricht deutsch|antwort.*deutsch|kommuni.*deutsch)\b", re.I),
                "Bevorzugt Antworten und Projektkommunikation auf Deutsch.",
            ),
            (
                re.compile(r"\b(read|lesen|erst lesen|before (making )?changes)\b", re.I),
                "Bei Code-/Dateiänderungen zuerst bestehende Dateien lesen.",
            ),
            (
                re.compile(r"\b(test|verify|verifizier|prüf|run.*tests)\b", re.I),
                "Änderungen nach der Umsetzung testen oder verifizieren.",
            ),
            (
                re.compile(r"\b(clean|light|hell|gradient|nüchtern|technical|ui|webgui)\b", re.I),
                "Bevorzugt helle, cleane, technische UIs ohne verspielte Elemente oder Gradients.",
            ),
            (
                re.compile(r"\b(rate.?limit|ratelimit|codex.*limit)\b", re.I),
                "Möchte Rate-Limit-Informationen direkt in Zuse sehen.",
            ),
            (
                re.compile(r"\b(zuse-web|webgui getrennt|cli-start|terminal-repl)\b", re.I),
                "Möchte `zuse` für die Terminal-REPL und `zuse-web` getrennt für die WebGUI halten.",
            ),
            (
                re.compile(r"\b(memory|preferences|gespeichert|sichtbar|block|<memory>)\b", re.I),
                "Möchte gespeicherte Preferences intern nutzen, aber nicht jedes Mal sichtbar im Chat anzeigen.",
            ),
        ]

        canonical: dict[str, Entry] = {}
        new_entries: list[Entry] = []
        removed = 0

        for entry in self.entries:
            if entry.kind != "preference":
                new_entries.append(entry)
                continue

            replacement = None
            for pattern, text in patterns:
                if pattern.search(entry.text):
                    replacement = text
                    break

            if replacement is None:
                new_entries.append(entry)
                continue

            if replacement in canonical:
                canonical[replacement].uses += entry.uses + 1
                canonical[replacement].tags = sorted(set(canonical[replacement].tags) | set(entry.tags))
                removed += 1
                continue

            entry.text = replacement
            canonical[replacement] = entry
            new_entries.append(entry)

        if removed:
            self.entries = new_entries
            self._save()
        elif any(e.kind == "preference" and e.text in canonical for e in self.entries):
            self.entries = new_entries
            self._save()
        return removed

    # -- reading -----------------------------------------------------------

    def preferences(self) -> list[Entry]:
        return [e for e in self.entries if e.kind == "preference"]

    def recall(self, query: str, k: int = 6, kinds: tuple[str, ...] | None = None) -> list[Entry]:
        pool = [e for e in self.entries if kinds is None or e.kind in kinds]
        if not pool:
            return []
        q_emb = self.embedder.embed(query) if self.embedder is not None else None
        q_tok = _tokens(query)

        scored: list[tuple[float, Entry]] = []
        for e in pool:
            if q_emb and e.embedding:
                score = _cosine(q_emb, e.embedding)
            else:
                score = _overlap(q_tok, e.tokens())
            if e.kind == "preference":
                score += 0.05  # gently favor durable preferences
            scored.append((score, e))

        scored.sort(key=lambda t: t[0], reverse=True)
        hits = [e for s, e in scored if s >= _RECALL_FLOOR][:k]
        for e in hits:
            e.uses += 1
        if hits:
            self._save()
        return hits

    def stats(self) -> dict[str, int]:
        out = {kind: 0 for kind in KINDS}
        for e in self.entries:
            out[e.kind] = out.get(e.kind, 0) + 1
        out["total"] = len(self.entries)
        return out
