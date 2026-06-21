"""Guards for the streaming HTTP backends."""

import pathlib

import httpx

import zuse.providers as providers
from zuse.providers.base import STREAM_TIMEOUT


def test_stream_timeout_is_finite():
    # A finite read timeout is what stops a stalled stream from hanging forever.
    assert isinstance(STREAM_TIMEOUT, httpx.Timeout)
    assert STREAM_TIMEOUT.read and STREAM_TIMEOUT.read > 0
    assert STREAM_TIMEOUT.connect and STREAM_TIMEOUT.connect > 0


def test_no_backend_streams_with_unbounded_timeout():
    # Regression guard: httpx.Client(timeout=None) hangs forever on a stalled
    # stream — the cause of an earlier "Zuse hung" report on the codex backend.
    provider_dir = pathlib.Path(providers.__file__).parent
    offenders = [
        f.name
        for f in provider_dir.glob("*_backend.py")
        if "timeout=None" in f.read_text()
    ]
    assert not offenders, f"backends stream with timeout=None (hang forever): {offenders}"
