"""EditJournal: undo of file creates, modifies, and deletes."""

from zuse.journal import EditJournal


def test_nothing_to_undo():
    j = EditJournal()
    assert not j.can_undo()
    assert "nothing to undo" in j.undo_last().lower()


def test_undo_modify_restores_prior_content(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("old")
    j = EditJournal()
    j.record(f, "old", "new")
    f.write_text("new")

    assert j.can_undo()
    j.undo_last()
    assert f.read_text() == "old"
    assert not j.can_undo()


def test_undo_create_removes_the_file(tmp_path):
    f = tmp_path / "new.txt"
    j = EditJournal()
    j.record(f, None, "hi")
    f.write_text("hi")

    j.undo_last()
    assert not f.exists()


def test_undo_delete_restores_the_file(tmp_path):
    f = tmp_path / "gone.txt"
    f.write_text("data")
    j = EditJournal()
    j.record(f, "data", None)
    f.unlink()

    j.undo_last()
    assert f.read_text() == "data"


def test_undo_is_lifo(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    j = EditJournal()
    j.record(a, None, "1")
    j.record(b, None, "2")
    summary = j.summary()
    assert len(summary) == 2
    # Most recent edit (b) undoes first.
    assert "b" in j.undo_last()
    assert "a" in j.undo_last()
