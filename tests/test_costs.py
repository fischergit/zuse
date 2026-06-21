"""Usage accumulation and cost accounting."""

from types import SimpleNamespace

import pytest

from zuse.config import PRICING
from zuse.costs import Usage


def _usage(**kw):
    base = dict(
        input_tokens=0, output_tokens=0,
        cache_read_input_tokens=0, cache_creation_input_tokens=0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_add_accumulates_across_calls():
    u = Usage()
    u.add(_usage(input_tokens=10, output_tokens=5, cache_read_input_tokens=2))
    u.add(_usage(input_tokens=20, output_tokens=7, cache_creation_input_tokens=3))
    assert u.requests == 2
    assert u.input_tokens == 30
    assert u.output_tokens == 12
    assert u.cache_read_tokens == 2
    assert u.cache_creation_tokens == 3


def test_add_tolerates_missing_fields():
    u = Usage()
    u.add(SimpleNamespace())  # nothing set
    assert u.requests == 1
    assert u.input_tokens == 0


def test_unknown_model_is_free():
    u = Usage()
    u.add(_usage(input_tokens=1_000_000, output_tokens=1_000_000))
    assert u.cost("totally-not-a-real-model") == 0.0
    assert "cost untracked" in u.summary("totally-not-a-real-model")


def test_priced_model_has_positive_cost():
    if not PRICING:
        pytest.skip("no pricing table")
    model = next(iter(PRICING))
    u = Usage()
    u.add(_usage(input_tokens=1_000_000, output_tokens=1_000_000))
    assert u.cost(model) > 0
