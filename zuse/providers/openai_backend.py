"""OpenAI-compatible backend (chat/completions over httpx).

Works with the OpenAI API, OpenRouter, Together, and any OpenAI-compatible
endpoint via base_url + API key. Streaming, tool calling, and usage accounting.

When configured with Codex "Sign in with ChatGPT" credentials, it talks to the
Codex Responses backend instead — see codex_backend.py.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx

from ..config import Config
from .base import Backend, StepResult, StreamSink, ToolCall, ToolResult


class OpenAIBackend(Backend):
    label = "openai"
    supports_web = False

    def __init__(self, config: Config, api_key: str, base_url: str, model: str,
                 cost_model: str | None = None) -> None:
        super().__init__()
        self.config = config
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.cost_model = cost_model  # only set for models we have pricing for

    # -- history -----------------------------------------------------------

    def context_window(self) -> int | None:
        m = self.model.lower()
        if m.startswith(("gpt-4.1", "o3", "o4")):
            return 1_000_000 if m.startswith("gpt-4.1") else 200_000
        if m.startswith(("gpt-5", "o1")):
            return 200_000
        if m.startswith(("gpt-4o", "gpt-4-turbo", "chatgpt-4o")):
            return 128_000
        return 128_000  # safe default for unknown OpenAI-compatible models

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, result: StepResult) -> None:
        self.messages.append(result.raw)

    def add_tool_results(self, results: list[ToolResult]) -> None:
        for r in results:
            content = r.content if not r.is_error else f"ERROR: {r.content}"
            self.messages.append({
                "role": "tool",
                "tool_call_id": r.tool_call_id,
                "content": content,
            })

    # -- generation --------------------------------------------------------

    def _tools(self, client_tools: list[dict]) -> list[dict]:
        return [
            {"type": "function", "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["input_schema"],
            }}
            for t in client_tools
        ]

    def generate(self, system, tools, view: StreamSink, effort=None, think=None) -> StepResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *self.messages],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = self._tools(tools)

        text_parts: list[str] = []
        # tool calls accumulate by streamed index
        tool_acc: dict[int, dict] = {}
        usage = SimpleNamespace(input_tokens=0, output_tokens=0,
                                cache_read_input_tokens=0, cache_creation_input_tokens=0)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        try:
            with httpx.Client(timeout=None) as client:
                with client.stream("POST", f"{self.base_url}/chat/completions",
                                   json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        body = resp.read().decode(errors="replace")
                        raise RuntimeError(f"OpenAI API {resp.status_code}: {body[:300]}")
                    for line in resp.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if chunk.get("usage"):
                            u = chunk["usage"]
                            usage.input_tokens = u.get("prompt_tokens", 0) or 0
                            usage.output_tokens = u.get("completion_tokens", 0) or 0
                        for choice in chunk.get("choices", []):
                            delta = choice.get("delta", {})
                            if content := delta.get("content"):
                                text_parts.append(content)
                                view.on_text(content)
                            for tc in delta.get("tool_calls", []) or []:
                                idx = tc.get("index", 0)
                                slot = tool_acc.setdefault(
                                    idx, {"id": "", "name": "", "args": ""})
                                if tc.get("id"):
                                    slot["id"] = tc["id"]
                                fn = tc.get("function", {})
                                if fn.get("name"):
                                    slot["name"] = fn["name"]
                                if fn.get("arguments"):
                                    slot["args"] += fn["arguments"]
        except httpx.ConnectError as e:
            raise RuntimeError(f"Cannot reach OpenAI endpoint {self.base_url}: {e}")

        text = "".join(text_parts)
        tool_calls: list[ToolCall] = []
        raw_tool_calls: list[dict] = []
        for idx in sorted(tool_acc):
            slot = tool_acc[idx]
            if not slot["name"]:
                continue
            try:
                args = json.loads(slot["args"]) if slot["args"].strip() else {}
            except json.JSONDecodeError:
                args = {}
            call_id = slot["id"] or f"call_{idx}"
            tool_calls.append(ToolCall(id=call_id, name=slot["name"], input=args))
            raw_tool_calls.append({
                "id": call_id, "type": "function",
                "function": {"name": slot["name"], "arguments": slot["args"] or "{}"},
            })

        raw: dict[str, Any] = {"role": "assistant", "content": text or None}
        if raw_tool_calls:
            raw["tool_calls"] = raw_tool_calls

        return StepResult(
            text=text,
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
            usage=usage,
            raw=raw,
        )

    # -- persistence -------------------------------------------------------

    def export(self) -> list[dict]:
        return list(self.messages)

    def load(self, data: list[dict]) -> None:
        self.messages = list(data)

    def transcript_text(self) -> str:
        out = []
        for msg in self.messages:
            role = msg.get("role", "?")
            if content := msg.get("content"):
                out.append(f"{role}: {content}")
            for tc in msg.get("tool_calls", []) or []:
                fn = tc.get("function", {})
                out.append(f"{role}: [called {fn.get('name')} {fn.get('arguments')}]")
        return "\n".join(out)

    def reset_with_summary(self, summary: str) -> None:
        self.messages = [{
            "role": "user",
            "content": f"Summary of the conversation so far (for your context):\n{summary}",
        }]
