from pathlib import Path

import pytest
from rich.console import Console

from zuse.config import Config
from zuse.journal import EditJournal
from zuse.permissions import PermissionManager
from zuse.tools.base import ToolContext, ToolError
from zuse.tools.filesystem import EditFile, Glob, Grep, ReadFile, WriteFile


def make_ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        cwd=tmp_path,
        console=Console(file=None),
        permissions=PermissionManager(Console(file=None), yolo=True),
        config=Config(),
        journal=EditJournal(),
    )


def test_read_file_with_line_numbers_and_range(tmp_path):
    ctx = make_ctx(tmp_path)
    (tmp_path / "sample.txt").write_text("one\ntwo\nthree\n")

    output = ReadFile().run({"path": "sample.txt", "start_line": 2, "end_line": 3}, ctx)

    assert output == "2  two\n3  three"


def test_write_and_edit_file_record_journal_and_support_undo(tmp_path):
    ctx = make_ctx(tmp_path)

    assert "Created" in WriteFile().run({"path": "note.txt", "content": "hello"}, ctx)
    assert (tmp_path / "note.txt").read_text() == "hello"

    assert "Edited" in EditFile().run(
        {"path": "note.txt", "old_string": "hello", "new_string": "hello world"}, ctx
    )
    assert (tmp_path / "note.txt").read_text() == "hello world"

    assert ctx.journal is not None
    assert ctx.journal.can_undo()
    ctx.journal.undo_last()
    assert (tmp_path / "note.txt").read_text() == "hello"


def test_edit_file_requires_unique_match_unless_replace_all(tmp_path):
    ctx = make_ctx(tmp_path)
    (tmp_path / "dupes.txt").write_text("x x")

    with pytest.raises(ToolError, match="appears 2 times"):
        EditFile().run({"path": "dupes.txt", "old_string": "x", "new_string": "y"}, ctx)

    EditFile().run(
        {"path": "dupes.txt", "old_string": "x", "new_string": "y", "replace_all": True}, ctx
    )
    assert (tmp_path / "dupes.txt").read_text() == "y y"


def test_glob_and_grep_ignore_vendor_dirs(tmp_path):
    ctx = make_ctx(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('needle')\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.py").write_text("needle\n")

    assert Glob().run({"path": ".", "pattern": "**/*.py"}, ctx) == "src/app.py"
    assert Grep().run({"path": ".", "pattern": "needle", "glob": "*.py"}, ctx) == (
        "src/app.py:1: print('needle')"
    )
