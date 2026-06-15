"""Edit journal for undo/checkpoints.

Every file-changing tool records the file's prior content here before writing,
so changes can be reverted with /undo — works in any directory, no git needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Edit:
    path: Path
    before: str | None   # prior content; None if the file did not exist
    after: str | None     # new content; None if the file was deleted
    kind: str             # "create" | "modify" | "delete"


class EditJournal:
    def __init__(self) -> None:
        self.entries: list[Edit] = []

    def record(self, path: Path, before: str | None, after: str | None) -> None:
        if before is None:
            kind = "create"
        elif after is None:
            kind = "delete"
        else:
            kind = "modify"
        self.entries.append(Edit(Path(path), before, after, kind))

    def can_undo(self) -> bool:
        return bool(self.entries)

    def undo_last(self) -> str:
        """Revert the most recent recorded edit. Returns a description."""
        if not self.entries:
            return "Nothing to undo."
        e = self.entries.pop()
        if e.kind == "create":
            # File was created → remove it to undo.
            try:
                e.path.unlink(missing_ok=True)
            except OSError as exc:
                return f"Could not undo (remove {e.path}): {exc}"
            return f"Undid creation of {e.path}"
        # modify or delete → restore the prior content.
        try:
            e.path.parent.mkdir(parents=True, exist_ok=True)
            e.path.write_text(e.before or "")
        except OSError as exc:
            return f"Could not undo (restore {e.path}): {exc}"
        return f"Reverted {e.path} to its previous content"

    def summary(self) -> list[str]:
        glyph = {"create": "＋", "modify": "~", "delete": "－"}
        return [f"{glyph.get(e.kind, '~')} {e.path}" for e in self.entries]
