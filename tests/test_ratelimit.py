from types import SimpleNamespace

from rich.console import Console

from zuse.cli import (
    _codex_rate_limit_status,
    _format_reset,
    _rate_limit_summary,
    _render_rate_limit_warning,
    _render_rate_limits,
)
from zuse.config import Config


class DummyBackend:
    def __init__(self, used_percent=75.0, remaining=25):
        self.used_percent = used_percent
        self.remaining = remaining

    def rate_limit_status(self):
        return {
            "provider": "codex",
            "limits": [
                {
                    "name": "requests",
                    "limit": 100,
                    "remaining": self.remaining,
                    "reset_seconds": 90,
                    "used_percent": self.used_percent,
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


def test_rate_limit_summary_for_prompt_toolbar():
    agent = SimpleNamespace(config=Config(provider="codex"), backend=DummyBackend())

    assert _rate_limit_summary(agent) == "rate-limit: requests 75% (25/100)"


def test_render_rate_limit_warning_at_threshold():
    agent = SimpleNamespace(config=Config(provider="codex"), backend=DummyBackend(used_percent=85.0, remaining=15))
    console = Console(record=True, force_terminal=False, width=100)

    _render_rate_limit_warning(agent, console)
    text = console.export_text()

    assert "Codex rate-limit warning" in text
    assert "requests 85%" in text
