"""Token usage and cost accounting."""

from __future__ import annotations

from dataclasses import dataclass

from .config import PRICING


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    requests: int = 0

    def add(self, usage_obj) -> None:
        """Accumulate from an Anthropic `usage` object."""
        self.requests += 1
        self.input_tokens += getattr(usage_obj, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage_obj, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage_obj, "cache_read_input_tokens", 0) or 0
        self.cache_creation_tokens += getattr(usage_obj, "cache_creation_input_tokens", 0) or 0

    def cost(self, model: str | None) -> float:
        price = PRICING.get(model or "")
        if price is None:  # local / unknown model → free
            return 0.0
        in_rate = price["input"] / 1_000_000
        out_rate = price["output"] / 1_000_000
        return (
            self.input_tokens * in_rate
            + self.output_tokens * out_rate
            + self.cache_read_tokens * in_rate * 0.1
            + self.cache_creation_tokens * in_rate * 1.25
        )

    def summary(self, model: str | None) -> str:
        total_in = self.input_tokens + self.cache_read_tokens + self.cache_creation_tokens
        cached_pct = 0
        if total_in:
            cached_pct = round(100 * self.cache_read_tokens / total_in)
        is_free = PRICING.get(model or "") is None
        tail = "cost untracked" if is_free else f"${self.cost(model):.4f}"
        cache_note = f" ({cached_pct}% cached)" if self.cache_read_tokens else ""
        return (
            f"{self.requests} requests · "
            f"{total_in:,} in{cache_note} · "
            f"{self.output_tokens:,} out · "
            f"{tail}"
        )
