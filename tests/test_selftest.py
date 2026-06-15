from types import SimpleNamespace

from zuse.cli import _run_selftest
from zuse.config import Config
from zuse.journal import EditJournal
from zuse.permissions import PermissionManager
from zuse.shell import BackgroundManager, ShellSession
from zuse.tools import ToolContext


class DummyConsole:
    def __init__(self):
        self.items = []

    def print(self, *args, **kwargs):
        self.items.extend(args)


def test_run_selftest_exercises_core_tools(tmp_path):
    console = DummyConsole()
    ctx = ToolContext(
        cwd=tmp_path,
        console=console,
        permissions=PermissionManager(console, yolo=True),
        config=Config(provider="ollama"),
        shell=ShellSession(tmp_path),
        background=BackgroundManager(tmp_path / "bg"),
        journal=EditJournal(),
    )
    agent = SimpleNamespace(ctx=ctx)

    try:
        assert _run_selftest(agent, console) is True
    finally:
        ctx.shell.kill()
        ctx.background.shutdown()

    titles = [getattr(item, "title", "") for item in console.items]
    assert "Zuse selftest" in titles
