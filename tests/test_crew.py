"""Parallel crew execution, exercised offline with a stub backend."""

from pathlib import Path

from rich.console import Console

from zuse.agent import Agent
from zuse.config import Config
from zuse.costs import Usage
from zuse.journal import EditJournal
from zuse.providers.base import Backend, StepResult
from zuse.tools import ToolContext


class FakeBackend(Backend):
    """Returns its last user message verbatim and calls no tools, so each
    specialist finishes in a single step. Echoing the prompt lets the test
    trace which task each report came from."""

    label = "fake"

    def __init__(self) -> None:
        super().__init__()
        self._last_user = ""

    def add_user(self, text: str) -> None:
        self._last_user = text
        self.messages.append(("user", text))

    def add_assistant(self, result: StepResult) -> None:
        self.messages.append(("assistant", result.text))

    def add_tool_results(self, results) -> None:
        self.messages.append(("tools", results))

    def generate(self, system, tools, view, effort=None, think=None) -> StepResult:
        return StepResult(text=self._last_user, tool_calls=[], usage=None)

    def export(self):
        return []

    def load(self, data) -> None:
        pass

    def transcript_text(self) -> str:
        return ""

    def reset_with_summary(self, summary: str) -> None:
        pass


def _reply_backend(reply: str):
    """A backend whose generate() always returns a fixed reply (for the router)."""
    backend = FakeBackend()
    backend.generate = lambda system, tools, view, effort=None, think=None: StepResult(
        text=reply, tool_calls=[], usage=None
    )
    return backend


def _make_agent() -> Agent:
    """Build an Agent with only the attributes `_run_crew` needs — avoids the
    heavyweight real constructor (MCP, knowledge files, browser, etc.)."""
    agent = Agent.__new__(Agent)
    agent.backend_factory = FakeBackend
    agent.config = Config(crew_planner=False, crew_concurrency=4)
    agent.console = Console(record=True, force_terminal=False, width=120)
    agent.usage = Usage()
    agent.knowledge = None
    agent.background = None
    agent.journal = EditJournal()
    agent.browser = None
    agent.tools = []  # specialists get no tools → they finish immediately
    agent._crew_permissions = None
    agent.ctx = ToolContext(
        cwd=Path.cwd(),
        console=agent.console,
        permissions=None,
        config=agent.config,
    )
    return agent


def test_run_crew_runs_all_specialists_and_preserves_order():
    agent = _make_agent()
    tasks = [
        {"role": "researcher", "title": "Map code", "instructions": "research", "max_steps": 2},
        {"role": "coder", "title": "Implement", "instructions": "code it", "max_steps": 2},
        {"role": "tester", "title": "Verify", "instructions": "test it", "max_steps": 2},
    ]

    result = agent._run_crew("Build a feature", tasks, mode="auto", max_steps=2)

    # Every specialist contributed, and report order matches task order even
    # though they complete on different threads.
    for role in ("researcher", "coder", "tester"):
        assert role in result
    assert (
        result.index("1. researcher")
        < result.index("2. coder")
        < result.index("3. tester")
    )
    # Parallel specialists + the synthesis step all accrued usage.
    assert agent.usage.requests >= len(tasks)


def test_run_crew_command_prints_a_report():
    agent = _make_agent()
    agent.run_crew("Investigate the build")  # the /crew command path

    text = agent.console.export_text()
    # The synthesized report was rendered, and the default crew roles appear.
    assert "zuse" in text
    assert "planner" in text or "researcher" in text


def test_auto_crew_router_decides_solo_vs_crew():
    agent = _make_agent()
    agent.config.auto_crew = True
    long_task = "please refactor the whole authentication system across many files"

    # Trivially short input stays solo without even consulting the model.
    assert agent._should_auto_crew("do it") is False

    # Router verdicts are honoured.
    agent.backend_factory = lambda: _reply_backend("solo")
    assert agent._should_auto_crew(long_task) is False
    agent.backend_factory = lambda: _reply_backend("crew")
    assert agent._should_auto_crew(long_task) is True

    # Disabled → never auto-crew.
    agent.config.auto_crew = False
    assert agent._should_auto_crew(long_task) is False


def test_auto_crew_turn_synthesizes_via_main_backend():
    agent = _make_agent()
    agent.system = "system"
    agent._turn_memory = ""
    agent.backend = _reply_backend("FINAL CREW ANSWER")  # the main turn's synthesis

    text = agent._auto_crew_turn("Audit and harden the installer")

    assert text == "FINAL CREW ANSWER"
    # The synthesis was recorded as a real assistant turn on the main backend.
    assert ("assistant", "FINAL CREW ANSWER") in agent.backend.messages


def test_run_crew_survives_a_failing_specialist():
    agent = _make_agent()

    real_subloop = agent._agent_subloop

    def flaky(role, title, instructions, max_steps, ctx, registry=None, rid=None):
        if role == "coder":
            raise RuntimeError("kaboom")
        return real_subloop(role, title, instructions, max_steps, ctx, registry, rid)

    agent._agent_subloop = flaky

    tasks = [
        {"role": "researcher", "title": "Map", "instructions": "x", "max_steps": 2},
        {"role": "coder", "title": "Impl", "instructions": "y", "max_steps": 2},
    ]
    result = agent._run_crew("Goal", tasks, mode="auto", max_steps=2)

    # The crew still returns a combined report; the failure is captured inline.
    assert "researcher" in result
    assert "failed" in result.lower() or "kaboom" in result
