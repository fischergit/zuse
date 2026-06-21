"""Saving and loading conversations."""

import zuse.session as session


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "SESSIONS_DIR", tmp_path)
    messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]

    session.save_session("demo", messages, "anthropic", "claude-x")
    data = session.load_session("demo")

    assert data["messages"] == messages
    assert data["provider"] == "anthropic"
    assert data["model"] == "claude-x"


def test_list_sessions_includes_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "SESSIONS_DIR", tmp_path)
    session.save_session("one", [], "ollama", "qwen")
    session.save_session("two", [], "openai", "gpt")

    names = [row[0] for row in session.list_sessions()]
    assert "one" in names and "two" in names
