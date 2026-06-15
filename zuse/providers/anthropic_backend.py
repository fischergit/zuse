"""Anthropic API backend: streaming, prompt caching, adaptive thinking, effort."""

from __future__ import annotations

from typing import Any

from ..config import Config
from .base import Backend, StepResult, StreamSink, ToolCall, ToolResult

_REASONING_MODELS = {
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
}


def _block_to_dict(block: Any) -> dict:
    if isinstance(block, dict):
        return block
    if hasattr(block, "to_dict"):
        return block.to_dict()
    if hasattr(block, "model_dump"):
        return block.model_dump()
    return {"type": "text", "text": str(block)}


class AnthropicBackend(Backend):
    label = "anthropic"
    supports_web = True

    def __init__(self, client, config: Config) -> None:
        super().__init__()
        self.client = client
        self.config = config
        self.cost_model = config.model

    # -- history -----------------------------------------------------------

    def context_window(self) -> int | None:
        return 1_000_000  # Claude 4.x models (opus/sonnet) provide a 1M window

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, result: StepResult) -> None:
        # result.raw is the SDK response content (list of blocks)
        self.messages.append({"role": "assistant", "content": result.raw})

    def add_tool_results(self, results: list[ToolResult]) -> None:
        blocks = []
        for r in results:
            if r.images:
                content: Any = [{"type": "text", "text": r.content}]
                for img in r.images:
                    content.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": img},
                    })
            else:
                content = r.content
            block = {"type": "tool_result", "tool_use_id": r.tool_call_id, "content": content}
            if r.is_error:
                block["is_error"] = True
            blocks.append(block)
        self.messages.append({"role": "user", "content": blocks})

    # -- generation --------------------------------------------------------

    def _tools(self, client_tools: list[dict]) -> list[dict]:
        tools = list(client_tools)
        if self.config.enable_web:
            tools.append({"type": "web_search_20260209", "name": "web_search"})
            tools.append({"type": "web_fetch_20260209", "name": "web_fetch"})
        return tools

    def generate(self, system, tools, view: StreamSink, effort=None, think=None) -> StepResult:
        self.cost_model = self.config.model  # keep in sync with /model switches
        want_thinking = self.config.thinking if think is None else think
        params: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "system": [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ],
            "tools": self._tools(tools),
            "messages": self.messages,
        }
        if self.config.model in _REASONING_MODELS:
            if want_thinking:
                params["thinking"] = {
                    "type": "adaptive",
                    "display": "summarized" if self.config.show_thinking else "omitted",
                }
            params["output_config"] = {"effort": effort or self.config.effort}

        with self.client.messages.stream(**params) as stream:
            for event in stream:
                if getattr(event, "type", "") == "content_block_delta":
                    delta = event.delta
                    dtype = getattr(delta, "type", "")
                    if dtype == "thinking_delta":
                        view.on_thinking(delta.thinking)
                    elif dtype == "text_delta":
                        view.on_text(delta.text)
            final = stream.get_final_message()

        text = "".join(b.text for b in final.content if getattr(b, "type", None) == "text")
        tool_calls = [
            ToolCall(id=b.id, name=b.name, input=b.input or {})
            for b in final.content
            if getattr(b, "type", None) == "tool_use"
        ]
        return StepResult(
            text=text,
            tool_calls=tool_calls,
            stop_reason=final.stop_reason,
            usage=final.usage,
            raw=final.content,
        )

    # -- persistence -------------------------------------------------------

    def export(self) -> list[dict]:
        out = []
        for msg in self.messages:
            content = msg["content"]
            if isinstance(content, str):
                out.append({"role": msg["role"], "content": content})
            else:
                out.append({"role": msg["role"], "content": [_block_to_dict(b) for b in content]})
        return out

    def load(self, data: list[dict]) -> None:
        self.messages = list(data)

    def transcript_text(self) -> str:
        out = []
        for msg in self.messages:
            role = msg["role"]
            content = msg["content"]
            if isinstance(content, str):
                out.append(f"{role}: {content}")
                continue
            for b in content:
                d = _block_to_dict(b)
                t = d.get("type")
                if t == "text":
                    out.append(f"{role}: {d.get('text', '')}")
                elif t == "tool_use":
                    out.append(f"{role}: [called {d.get('name')} {d.get('input')}]")
                elif t == "tool_result":
                    c = d.get("content")
                    txt = c if isinstance(c, str) else "[non-text result]"
                    out.append(f"tool: {txt}")
        return "\n".join(out)

    def reset_with_summary(self, summary: str) -> None:
        self.messages = [{
            "role": "user",
            "content": f"Summary of the conversation so far (for your context):\n{summary}",
        }]
