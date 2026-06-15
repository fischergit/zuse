import json

from zuse import config as config_module
from zuse.config import Config, load_project_instructions, resolve_model


def test_resolve_model_aliases_and_passthrough():
    assert resolve_model("opus") == "claude-opus-4-8"
    assert resolve_model("custom-model") == "custom-model"
    assert resolve_model(None) == "claude-opus-4-8"


def test_config_load_ignores_unknown_keys_and_applies_env_overrides(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"provider": "ollama", "unknown": "ignored"}))
    monkeypatch.setattr(config_module, "CONFIG_FILE", cfg_file)
    monkeypatch.setenv("ZUSE_MODEL", "sonnet")
    monkeypatch.setenv("OLLAMA_HOST", "localhost:11434")

    cfg = Config.load()

    assert cfg.provider == "ollama"
    assert cfg.model == "claude-sonnet-4-6"
    assert cfg.ollama_host == "http://localhost:11434"
    assert not hasattr(cfg, "unknown")


def test_config_save_writes_json(tmp_path, monkeypatch):
    cfg_file = tmp_path / "nested" / "config.json"
    monkeypatch.setattr(config_module, "CONFIG_DIR", tmp_path / "nested")
    monkeypatch.setattr(config_module, "SESSIONS_DIR", tmp_path / "nested" / "sessions")
    monkeypatch.setattr(config_module, "CONFIG_FILE", cfg_file)

    cfg = Config(provider="ollama", local_model="qwen2.5-coder:7b")
    cfg.save()

    data = json.loads(cfg_file.read_text())
    assert data["provider"] == "ollama"
    assert data["local_model"] == "qwen2.5-coder:7b"


def test_load_project_instructions_stops_at_project_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module.Path, "home", lambda: tmp_path)
    project = tmp_path / "project"
    child = project / "src"
    child.mkdir(parents=True)
    (project / ".zuse.md").write_text("Use pytest.")

    assert load_project_instructions(child) == "Use pytest."
