from rich.console import Console

from zuse.ui import StreamView


def test_stream_view_prints_final_answer_once_with_transient_live():
    console = Console(record=True, force_terminal=False, width=100)

    with StreamView(console, markdown=True, show_thinking=False) as view:
        view.on_text("Erledigt — final answer")

    text = console.export_text()

    assert text.count("zuse") == 1
    assert text.count("Erledigt — final answer") == 1
