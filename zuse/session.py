"""Save and load conversation sessions to disk."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import SESSIONS_DIR, ensure_dirs


def save_session(name: str, messages: list, provider: str, model: str) -> Path:
    ensure_dirs()
    path = SESSIONS_DIR / f"{name}.json"
    payload = {
        "name": name,
        "provider": provider,
        "model": model,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "messages": messages,
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def load_session(name: str) -> dict:
    path = SESSIONS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(name)
    return json.loads(path.read_text())


def list_sessions() -> list[tuple[str, str, str]]:
    ensure_dirs()
    rows: list[tuple[str, str, str]] = []
    for path in sorted(SESSIONS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            rows.append((data.get("name", path.stem), data.get("provider", "?"),
                         data.get("saved_at", "?")))
        except (json.JSONDecodeError, OSError):
            rows.append((path.stem, "?", "?"))
    return rows
