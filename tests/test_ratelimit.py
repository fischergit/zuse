from types import SimpleNamespace

from rich.console import Console

from zuse.cli import _codex_rate_limit_status, _format_reset, _render_rate_limits
from zuse.config import Config


class DummyBackend:
    def rate_limit_status(self):
        return {
            "provider": "codex",
            "limits": [
                {
                    "name": "requests",
                    "limit": 100,
                    "remaining": 25,
                    "reset_seconds": 90,
                    "used_percent": 75.0,
                }
            ],
            "headers": {},
        }


def test_format_reset():
    assert _format_reset(None) == "—"
    assert _format_reset(42) == "42s"
    assert _format_reset(90) == "1m 30s"
    assert _format_reset(3660) == "1h 1m"


def test_codex_rate_limit_status_only_for_codex():
    agent = SimpleNamespace(config=Config(provider="ollama"), backend=DummyBackend())

    assert _codex_rate_limit_status(agent) is None


def test_render_rate_limits_outputs_table():
    agent = SimpleNamespace(config=Config(provider="codex"), backend=DummyBackend())
    console = Console(record=True, force_terminal=False, width=100)

    _render_rate_limits(agent, console)
    text = console.export_text()

    assert "Codex rate limit" in text
    assert "requests" in text
    assert "75%" in text
    assert "25 / 100" in text
