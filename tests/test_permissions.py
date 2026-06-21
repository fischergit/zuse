"""PermissionManager: yolo, prompting, and session 'always allow' memory."""

from zuse.permissions import Decision, PermissionManager


class FakeConsole:
    """Stands in for a rich Console: records prints, replays queued inputs."""

    def __init__(self, answers=None):
        self.answers = list(answers or [])
        self.prints = 0

    def print(self, *args, **kwargs):
        self.prints += 1

    def input(self, *args, **kwargs):
        return self.answers.pop(0) if self.answers else ""


def test_yolo_allows_without_prompting():
    console = FakeConsole()
    pm = PermissionManager(console, yolo=True)
    assert pm.request("bash", "bash", "$ ls") is Decision.ALLOW
    assert console.prints == 0  # never rendered a prompt


def test_no_answer_allows_once():
    pm = PermissionManager(FakeConsole(answers=[""]), yolo=False)
    assert pm.request("bash", "bash", "$ ls") is Decision.ALLOW


def test_deny_is_respected():
    pm = PermissionManager(FakeConsole(answers=["n"]), yolo=False)
    assert pm.request("bash", "bash", "$ rm x") is Decision.DENY


def test_always_allow_is_remembered_then_reset():
    console = FakeConsole(answers=["a"])
    pm = PermissionManager(console, yolo=False)
    # 'a' grants and remembers the tool for the session.
    assert pm.request("bash", "bash", "$ ls") is Decision.ALLOW
    # Subsequent calls allow without consuming another answer / prompting.
    prompts_after_grant = console.prints
    assert pm.request("bash", "bash", "$ ls") is Decision.ALLOW
    assert console.prints == prompts_after_grant

    pm.reset_session()
    console.answers = ["n"]
    assert pm.request("bash", "bash", "$ ls") is Decision.DENY
