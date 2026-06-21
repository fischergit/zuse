from rich.console import Console

from zuse import ui
from zuse.config import Config


def test_terminal_banner_is_clean_and_has_no_rate_limit_text():
    console = Console(record=True, force_terminal=False, width=100)
    cfg = Config(provider="codex", codex_model="gpt-test")

    ui.print_banner(console, cfg, "/Users/nik/project", animate=False, mcp_servers=0, context_limit=100000)
    text = console.export_text()

    assert "Zuse" in text
    assert "gpt-test" in text
    assert "rate" not in text.lower()
    assert "limit" not in text.lower()
