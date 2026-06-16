import argparse

from zuse import cli


def test_plain_zuse_starts_terminal_repl(monkeypatch):
    called = {"repl": False}

    class FakeAgent:
        project = ""

        def __init__(self, factory, cfg, console):
            self.config = cfg
            self.mcp = argparse.Namespace(servers=[])

        def _compact_threshold(self):
            return 0

        def shutdown(self):
            pass

    monkeypatch.setattr(cli, "_setup_backend", lambda cfg, console: (lambda: object()))
    monkeypatch.setattr(cli, "Agent", FakeAgent)
    monkeypatch.setattr(cli, "run_repl", lambda agent, console: called.__setitem__("repl", True))

    assert cli.main(["--provider", "codex"]) == 0
    assert called == {"repl": True}
