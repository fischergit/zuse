"""Optional local embeddings via Ollama, for semantic knowledge recall.

If no embedding model is configured/available, the knowledge store falls back
to keyword overlap — so this is a pure enhancement, never a requirement.
"""

from __future__ import annotations

import httpx


class OllamaEmbedder:
    def __init__(self, host: str, model: str) -> None:
        self.url = host.rstrip("/") + "/api/embeddings"
        self.model = model
        self._cache: dict[str, list[float]] = {}
        self._ok = True

    def embed(self, text: str) -> list[float] | None:
        if not self._ok:
            return None
        if text in self._cache:
            return self._cache[text]
        try:
            r = httpx.post(self.url, json={"model": self.model, "prompt": text}, timeout=20)
            r.raise_for_status()
            vec = r.json().get("embedding")
            if isinstance(vec, list) and vec:
                self._cache[text] = vec
                return vec
        except Exception:  # noqa: BLE001 — embeddings are best-effort
            self._ok = False  # stop trying after the first failure this session
        return None

    @staticmethod
    def available(host: str, model: str) -> bool:
        try:
            r = httpx.get(host.rstrip("/") + "/api/tags", timeout=4)
            names = [m["name"] for m in r.json().get("models", [])]
            return any(n == model or n.split(":")[0] == model for n in names)
        except Exception:  # noqa: BLE001
            return False
