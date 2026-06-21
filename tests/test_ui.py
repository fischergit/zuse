from rich.console import Console

from zuse.agentpool import AgentRegistry
from zuse.tools.base import TodoItem
from zuse.ui import CrewDashboard, StreamView, TurnProgress, _progress_bar


def test_stream_view_prints_final_answer_once_with_transient_live():
    console = Console(record=True, force_terminal=False, width=100)

    with StreamView(console, markdown=True, show_thinking=False) as view:
        view.on_text("Erledigt — final answer")

    text = console.export_text()

    assert text.count("zuse") == 1
    assert text.count("Erledigt — final answer") == 1


def test_progress_bar_fills_proportionally():
    assert _progress_bar(0.0, width=10) == "▱" * 10
    assert _progress_bar(1.0, width=10) == "▰" * 10
    assert _progress_bar(0.5, width=10) == "▰" * 5 + "▱" * 5


def test_crew_dashboard_renders_agents_with_status_and_progress():
    console = Console(record=True, force_terminal=False, width=120)
    reg = AgentRegistry()
    a = reg.create("researcher", "Map the codebase", 8)
    b = reg.create("coder", "Implement the feature", 10)
    c = reg.create("tester", "Run verification", 6)
    reg.start(a)
    reg.update(a, step=3, activity="grep · spawn_crew")
    reg.start(b)
    reg.finish(b, ok=True)
    reg.finish(c, ok=False, error="no tests found")

    with CrewDashboard(console, reg, "Build a feature"):
        pass

    text = console.export_text()
    # Title, every agent role, and the live counters are present.
    assert "crew" in text
    for role in ("researcher", "coder", "tester"):
        assert role in text
    assert "running" in text and "done" in text and "failed" in text
    # A progress bar was drawn.
    assert "▰" in text or "▱" in text
    # Per-agent percentages and an overall percentage are shown.
    assert "100%" in text          # the finished coder
    assert "% overall" in text


def test_turn_progress_shows_agent_label_and_todo_fraction():
    console = Console(record=True, force_terminal=False, width=80)
    todos = [
        TodoItem("a", "done"),
        TodoItem("b", "in_progress"),
        TodoItem("c", "pending"),
    ]
    progress = TurnProgress(console, todos, label="zuse", step=2)
    console.print(progress)  # render one frame

    text = console.export_text()
    assert "zuse" in text
    assert "33%" in text  # one of three todos done
    assert "1/3" in text


def test_turn_progress_falls_back_to_step_without_todos():
    console = Console(record=True, force_terminal=False, width=80)
    progress = TurnProgress(console, [], label="zuse", step=4)
    console.print(progress)

    assert "step 4" in console.export_text()
