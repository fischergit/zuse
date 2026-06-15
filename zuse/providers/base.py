"""Provider-neutral backend interface.

Each backend keeps its own native conversation history and translates the
shared `ToolCall` / `ToolResult` types to and from its wire format. The Agent
drives any backend through the same small surface: add_user → generate →
add_assistant → (execute tools) → add_tool_results.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResult:
    tool_call_id: str
    name: str
    content: str
    is_error: bool = False
    images: list[str] = field(default_factory=list)  # base64 PNG, for vision models


@dataclass
class StepResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: Any = None          # object with input_tokens/output_tokens attributes
    raw: Any = None            # backend-native assistant turn, for history fidelity


class StreamSink(Protocol):
    def on_text(self, delta: str) -> None: ...
    def on_thinking(self, delta: str) -> None: ...


class Backend(ABC):
    """Base class for a model provider. Holds the native message history."""

    label: str = "backend"
    supports_web: bool = False
    cost_model: str | None = None  # model id used for pricing, or None if free

    def __init__(self) -> None:
        self.messages: list[Any] = []

    # -- history -----------------------------------------------------------

    @abstractmethod
    def add_user(self, text: str) -> None: ...

    @abstractmethod
    def add_assistant(self, result: StepResult) -> None: ...

    @abstractmethod
    def add_tool_results(self, results: list[ToolResult]) -> None: ...

    def clear(self) -> None:
        self.messages = []

    def context_window(self) -> int | None:
        """The active model's input context window in tokens, or None if unknown.
        Used to size the auto-compaction threshold."""
        return None

    # -- generation --------------------------------------------------------

    @abstractmethod
    def generate(
        self,
        system: str,
        tools: list[dict[str, Any]],
        view: StreamSink,
        effort: str | None = None,
        think: bool | None = None,
    ) -> StepResult:
        """Run one model step against the current history, streaming output to
        `view`, and return the assistant's text and any tool calls."""

    # -- persistence -------------------------------------------------------

    @abstractmethod
    def export(self) -> list[dict[str, Any]]:
        """Return the history as JSON-serializable dicts."""

    @abstractmethod
    def load(self, data: list[dict[str, Any]]) -> None: ...

    # -- compaction --------------------------------------------------------

    @abstractmethod
    def transcript_text(self) -> str:
        """Render the full history as plain text, for summarization."""

    @abstractmethod
    def reset_with_summary(self, summary: str) -> None:
        """Replace the entire history with a single summary user-message."""
