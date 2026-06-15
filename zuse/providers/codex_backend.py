"""Codex Responses backend — uses the ChatGPT OAuth token against OpenAI's
Codex backend (chatgpt.com/backend-api/codex/responses).

EXPERIMENTAL: the Responses API + Codex backend are reverse-engineered and
unofficial for third-party apps. Non-streaming for robustness. If this stops
working, OpenAI likely changed the endpoint — prefer the API-key OpenAIBackend.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

import httpx

from ..config import Config
from ..openai_auth import CODEX_BASE_URL, get_access_token
from .base import Backend, StepResult, StreamSink, ToolCall, ToolResult


class CodexBackend(Backend):
    label = "codex"
    supports_web = False
    cost_model = None  # ChatGPT-plan usage, not per-token API billing

    def __init__(self, config: Config, model: str) -> None:
        super().__init__()
        self.config = config
        self.model = model
        self.session_id = str(uuid.uuid4())
        # self.messages holds Responses-API "input" items.

    # -- history (Responses input items) -----------------------------------

    def add_user(self, text: str) -> None:
        self.messages.append({
            "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": text}],
        })

    def add_assistant(self, result: StepResult) -> None:
        # result.raw is the list of output items the model produced.
        if result.raw:
            self.messages.extend(result.raw)

    def add_tool_results(self, results: list[ToolResult]) -> None:
        for r in results:
            out = r.content if not r.is_error else f"ERROR: {r.content}"
            self.messages.append({
                "type": "function_call_output",
                "call_id": r.tool_call_id,
                "output": out,
            })

    # -- generation --------------------------------------------------------

    def _tools(self, client_tools: list[dict]) -> list[dict]:
        return [
            {"type": "function", "name": t["name"],
             "description": t.get("description", ""),
             "parameters": t["input_schema"], "strict": False}
            for t in client_tools
        ]

    def generate(self, system, tools, view: StreamSink, effort=None, think=None) -> StepResult:
        token, account_id = get_access_token()
        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": self.messages,
            "stream": True,  # the Codex backend requires streaming
            "store": False,
        }
        if tools:
            payload["tools"] = self._tools(tools)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "originator": "codex_cli_rs",
            "session_id": self.session_id,
        }
        if account_id:
            headers["chatgpt-account-id"] = account_id

        streamed: list[str] = []
        output_items: list[dict] = []
        usage_obj: dict = {}

        try:
            with httpx.Client(timeout=None) as client:
                with client.stream("POST", f"{CODEX_BASE_URL}/responses",
                                   json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        body = resp.read().decode(errors="replace")
                        raise RuntimeError(f"Codex backend {resp.status_code}: {body[:300]}")
                    for line in resp.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            ev = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        etype = ev.get("type", "")
                        if etype == "response.output_text.delta":
                            delta = ev.get("delta", "")
                            if delta:
                                streamed.append(delta)
                                view.on_text(delta)
                        elif etype == "response.output_item.done":
                            # Finalized items (messages, function_calls) arrive here;
                            # response.completed.output is often empty for tool calls.
                            item = ev.get("item")
                            if item:
                                output_items.append(item)
                        elif etype in ("response.completed", "response.incomplete"):
                            response = ev.get("response", {})
                            if response.get("output"):
                                output_items = response["output"]  # authoritative if present
                            usage_obj = response.get("usage", {}) or usage_obj
                        elif etype in ("response.failed", "error"):
                            err = ev.get("response", {}).get("error") or ev.get("error") or {}
                            raise RuntimeError(f"Codex backend error: {err.get('message', ev)}")
        except httpx.ConnectError as e:
            raise RuntimeError(f"Cannot reach the Codex backend: {e}")

        # Prefer the authoritative final output items; fall back to streamed text.
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for item in output_items:
            itype = item.get("type")
            if itype == "message":
                for block in item.get("content", []):
                    if block.get("type") in ("output_text", "text"):
                        text_parts.append(block.get("text", ""))
            elif itype == "function_call":
                call_id = item.get("call_id") or item.get("id") or f"call_{len(tool_calls)}"
                try:
                    args = json.loads(item.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(id=call_id, name=item.get("name", ""), input=args))
        text = "".join(text_parts) or "".join(streamed)

        # Build history items to send back next turn. With store=false the server
        # cannot resolve its own ephemeral items (e.g. `reasoning` rs_… ids), so
        # keep only message/function_call items and strip server-assigned `id`s —
        # they then count as inline items rather than unresolved references.
        history_items = [
            {k: v for k, v in item.items() if k != "id"}
            for item in output_items
            if item.get("type") in ("message", "function_call")
        ]

        usage = SimpleNamespace(
            input_tokens=usage_obj.get("input_tokens", 0) or 0,
            output_tokens=usage_obj.get("output_tokens", 0) or 0,
            cache_read_input_tokens=0, cache_creation_input_tokens=0,
        )
        return StepResult(
            text=text,
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
            usage=usage,
            raw=history_items,  # cleaned items safe to resend with store=false
        )

    # -- persistence -------------------------------------------------------

    def export(self) -> list[dict]:
        return list(self.messages)

    def load(self, data: list[dict]) -> None:
        self.messages = list(data)

    def transcript_text(self) -> str:
        out = []
        for item in self.messages:
            t = item.get("type")
            if t == "message":
                texts = " ".join(b.get("text", "") for b in item.get("content", []))
                out.append(f"{item.get('role', '?')}: {texts}")
            elif t == "function_call":
                out.append(f"assistant: [called {item.get('name')} {item.get('arguments')}]")
            elif t == "function_call_output":
                out.append(f"tool: {item.get('output', '')}")
        return "\n".join(out)

    def reset_with_summary(self, summary: str) -> None:
        self.messages = [{
            "type": "message", "role": "user",
            "content": [{"type": "input_text",
                         "text": f"Summary of the conversation so far:\n{summary}"}],
        }]
