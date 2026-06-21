"""ShellSession: a persistent bash that keeps state across commands."""

from pathlib import Path

import pytest

from zuse.shell import ShellSession


@pytest.fixture
def shell():
    s = ShellSession(Path("/tmp"))
    yield s
    s.kill()


def test_runs_command_and_reports_exit_code(shell):
    out, code = shell.run("echo hello-zuse")
    assert "hello-zuse" in out
    assert code == 0


def test_nonzero_exit_code_is_captured(shell):
    _, code = shell.run("false")
    assert code == 1


def test_env_vars_persist_across_calls(shell):
    shell.run("export ZUSE_TEST=42")
    out, _ = shell.run("echo $ZUSE_TEST")
    assert "42" in out


def test_cwd_persists_across_calls(shell):
    shell.run("cd /")
    out, _ = shell.run("pwd")
    assert out.strip() == "/"
