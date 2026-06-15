from types import SimpleNamespace

from zuse.cli import _decide_provider
from zuse.config import Config


def args(**overrides):
    values = {"provider": None, "local": False}
    values.update(overrides)
    return SimpleNamespace(**values)


def test_decide_provider_honors_explicit_provider():
    assert _decide_provider(args(provider="openai"), Config(provider="anthropic")) == "openai"


def test_decide_provider_honors_local_flag():
    assert _decide_provider(args(local=True), Config(provider="codex")) == "ollama"


def test_decide_provider_honors_saved_non_anthropic_provider():
    assert _decide_provider(args(), Config(provider="codex")) == "codex"


def test_decide_provider_uses_anthropic_when_key_exists(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    assert _decide_provider(args(), Config(provider="anthropic")) == "anthropic"


def test_decide_provider_falls_back_to_ollama_without_anthropic_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    assert _decide_provider(args(), Config(provider="anthropic")) == "ollama"
