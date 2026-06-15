from types import SimpleNamespace

from zuse.cli import _run_doctor
from zuse.config import Config


class DummyConsole:
    def __init__(self):
        self.items = []

    def print(self, *args, **kwargs):
        self.items.extend(args)


def test_run_doctor_renders_health_table(monkeypatch):
    def fake_ollama(_cfg):
        return "ok", "test-model available"

    monkeypatch.setattr("zuse.cli._check_ollama", fake_ollama)
    cfg = Config(provider="ollama", local_model="test-model")
    agent = SimpleNamespace(
        config=cfg,
        mcp=SimpleNamespace(servers=[]),
        knowledge=SimpleNamespace(entries=[]),
    )
    console = DummyConsole()

    _run_doctor(agent, console)

    assert console.items
    table = console.items[0]
    assert table.title == "Zuse doctor"
    rendered_rows = [str(cell) for column in table.columns for cell in column._cells]
    assert "Ollama" in rendered_rows
    assert "test-model available" in rendered_rows
