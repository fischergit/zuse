"""Local model backend via Ollama's native /api/chat endpoint.

Runs fully offline against a model served by `ollama serve` (default
http://localhost:11434). Supports streaming, tool/function calling, token
accounting, and inline <think>…</think> reasoning extraction.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx

from ..config import Config
from .base import Backend, StepResult, StreamSink, ToolCall, ToolResult

_THINK_TAGS = ("<think>", "</think>")
_MAX_TAG = max(len(t) for t in _THINK_TAGS)


class _ThinkStream:
    """Routes streamed text to on_text / on_thinking, extracting <think> spans
    that some local models emit inline. Buffers across chunk boundaries so a tag
    split between two deltas is still detected."""

    def __init__(self, view: StreamSink, show_thinking: bool) -> None:
        self.view = view
        self.show = show_thinking
        self.buf = ""
        self.in_think = False
        self.text_out: list[str] = []

    def feed(self, chunk: str) -> None:
        if not chunk:
            return
        self.buf += chunk
        while True:
            idx, tag = self._find_tag()
            if idx is None:
                safe = self._safe_len()
                if safe:
                    self._emit(self.buf[:safe])
                    self.buf = self.buf[safe:]
                return
            if idx:
                self._emit(self.buf[:idx])
            self.in_think = tag == "<think>"
            self.buf = self.buf[idx + len(tag):]

    def _find_tag(self):
        best, best_tag = None, None
        for t in _THINK_TAGS:
            i = self.buf.find(t)
            if i != -1 and (best is None or i < best):
                best, best_tag = i, t
        return (best, best_tag) if best is not None else (None, None)

    def _safe_len(self) -> int:
        # Hold back a tail that could be the start of a split tag.
        for k in range(min(_MAX_TAG - 1, len(self.buf)), 0, -1):
            if any(t.startswith(self.buf[-k:]) for t in _THINK_TAGS):
                return len(self.buf) - k
        return len(self.buf)

    def _emit(self, text: str) -> None:
        if not text:
            return
        if self.in_think:
            if self.show:
                self.view.on_thinking(text)
        else:
            self.text_out.append(text)
            self.view.on_text(text)

    def flush(self) -> None:
        if self.buf:
            self._emit(self.buf)
            self.buf = ""

    def text(self) -> str:
        return "".join(self.text_out)


class OllamaBackend(Backend):
    label = "ollama"
    supports_web = False
    cost_model = None  # local → free

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.host = config.ollama_host.rstrip("/")
        self.model = config.local_model

    # -- discovery ---------------------------------------------------------

    @staticmethod
    def list_models(host: str) -> list[str]:
        host = host.rstrip("/")
        r = httpx.get(f"{host}/api/tags", timeout=5)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]

    @staticmethod
    def resolve_model(configured: str, available: list[str]) -> str | None:
        """Pick the best matching installed model, preferring a truly local one."""
        if not available:
            return None
        if configured in available:
            return configured
        for m in available:  # tag-prefix match: "qwen3.5" → "qwen3.5:0.8b"
            if m.split(":")[0] == configured or m.startswith(configured + ":"):
                return m
        local = [m for m in available if not m.endswith(":cloud")]
        return (local or available)[0]

    # -- history -----------------------------------------------------------

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, result: StepResult) -> None:
        self.messages.append(result.raw)

    def add_tool_results(self, results: list[ToolResult]) -> None:
        for r in results:
            content = r.content
            if r.is_error:
                content = f"ERROR: {content}"
            msg = {"role": "tool", "tool_name": r.name, "content": content}
            if r.images:
                msg["images"] = r.images
            self.messages.append(msg)

    # -- generation --------------------------------------------------------

    def _tools(self, client_tools: list[dict]) -> list[dict]:
        out = []
        for t in client_tools:
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t["input_schema"],
                    },
                }
            )
        return out

    def generate(self, system, tools, view: StreamSink, effort=None, think=None) -> StepResult:
        want_thinking = self.config.thinking if think is None else think
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *self.messages],
            "tools": self._tools(tools),
            "stream": True,
            "think": want_thinking,
            "options": {"num_ctx": 8192},
        }

        splitter = _ThinkStream(view, self.config.show_thinking)
        raw_tool_calls: list[dict] = []
        prompt_tokens = output_tokens = 0

        for attempt in range(2):
            raw_tool_calls.clear()
            splitter = _ThinkStream(view, self.config.show_thinking)
            try:
                with httpx.Client(timeout=None) as client:
                    with client.stream("POST", f"{self.host}/api/chat", json=payload) as resp:
                        if resp.status_code != 200:
                            body = resp.read().decode(errors="replace")
                            # Some models reject the `think` parameter — drop it and retry.
                            if attempt == 0 and "think" in body.lower() and "think" in payload:
                                payload.pop("think", None)
                                continue
                            raise RuntimeError(f"Ollama returned {resp.status_code}: {body[:300]}")
                        for line in resp.iter_lines():
                            if not line:
                                continue
                            obj = json.loads(line)
                            msg = obj.get("message", {})
                            if (thinking := msg.get("thinking")) and self.config.show_thinking:
                                view.on_thinking(thinking)
                            if content := msg.get("content"):
                                splitter.feed(content)
                            for tc in msg.get("tool_calls", []) or []:
                                raw_tool_calls.append(tc)
                            if obj.get("done"):
                                prompt_tokens = obj.get("prompt_eval_count", 0) or 0
                                output_tokens = obj.get("eval_count", 0) or 0
            except httpx.ConnectError as e:
                raise RuntimeError(
                    f"Cannot reach Ollama at {self.host}. Is it running? "
                    f"Start it with `ollama serve`. ({e})"
                )
            break

        splitter.flush()
        text = splitter.text()

        tool_calls: list[ToolCall] = []
        for i, tc in enumerate(raw_tool_calls):
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tool_calls.append(ToolCall(id=f"call_{len(self.messages)}_{i}", name=fn.get("name", ""), input=args))

        raw_assistant: dict[str, Any] = {"role": "assistant", "content": text}
        if raw_tool_calls:
            raw_assistant["tool_calls"] = raw_tool_calls

        usage = SimpleNamespace(
            input_tokens=prompt_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        return StepResult(
            text=text,
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
            usage=usage,
            raw=raw_assistant,
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
