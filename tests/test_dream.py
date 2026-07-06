from types import SimpleNamespace

from zuse import config as config_module
from zuse import session as session_module
from zuse.config import Config
from zuse.dream import DreamManager, append_improvements, parse_dream_json, recent_session_digest
from zuse.knowledge import KnowledgeStore
from zuse.providers.base import StepResult
from zuse.session import save_session


def test_parse_dream_json_extracts_json_object():
    raw = """
    notes before
    {"summary":"ok","lessons":[{"kind":"fact","text":"Zuse runs locally."}],"improvements":[]}
    notes after
    """

    parsed = parse_dream_json(raw)

    assert parsed["summary"] == "ok"
    assert parsed["lessons"][0]["text"] == "Zuse runs locally."


def test_recent_session_digest_reads_last_messages(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_module, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(session_module, "SESSIONS_DIR", tmp_path / "sessions")
    messages = [
        {"role": "user", "content": "Remember this project convention."},
        {"role": "assistant", "content": "Stored."},
    ]
    save_session("dream-demo", messages, "ollama", "qwen")

    digest = recent_session_digest(limit=1)

    assert "dream-demo" in digest
    assert "Remember this project convention." in digest


def test_append_improvements_dedupes_existing_items(tmp_path, monkeypatch):
    path = tmp_path / "improvements.md"
    monkeypatch.setattr(config_module, "IMPROVEMENTS_FILE", path)
    item = {"priority": "medium", "title": "Improve setup", "detail": "Make onboarding calmer."}

    append_improvements([item])
    append_improvements([item])

    text = path.read_text()
    assert text.count("Improve setup") == 1


def test_dream_manager_stores_lessons_and_improvements(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "DREAMS_FILE", tmp_path / "dreams.jsonl")
    monkeypatch.setattr(config_module, "IMPROVEMENTS_FILE", tmp_path / "improvements.md")
    monkeypatch.setattr(config_module, "SESSIONS_DIR", tmp_path / "sessions")
    store = KnowledgeStore(tmp_path / "knowledge.jsonl")

    class FakeBackend:
        def add_user(self, text):
            self.text = text

        def generate(self, system, tools, view, effort=None, think=None):
            return StepResult(
                text=(
                    '{"summary":"dreamed","lessons":[{"kind":"procedure",'
                    '"text":"Run focused tests after SwiftUI changes."}],'
                    '"improvements":[{"priority":"high","title":"Add dream UI",'
                    '"detail":"Expose dream status in clients."}]}'
                ),
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            )

    manager = DreamManager(
        backend_factory=FakeBackend,
        config=Config(dream_enabled=False),
        knowledge=store,
        active_transcript=lambda: "user: make Zuse better\nassistant: ok",
    )

    result = manager.run_once(force=True)

    assert result.summary == "dreamed"
    assert result.learned == [("procedure", "Run focused tests after SwiftUI changes.")]
    assert "Add dream UI" in (tmp_path / "improvements.md").read_text()
    assert (tmp_path / "dreams.jsonl").exists()
