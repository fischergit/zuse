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
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

KINDS = ("preference", "fact", "procedure")
_TOKEN = re.compile(r"[a-zA-Z0-9_]{3,}")
_DUP_THRESHOLD = 0.82
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
