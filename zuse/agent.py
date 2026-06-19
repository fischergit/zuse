"""Core agentic loop: provider-neutral, with tool execution, sub-agents, and a
continuous-learning knowledge store (recall before each task, reflect after)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from rich.console import Console

from . import ui
from .config import (
    CONFIG_DIR,
    KNOWLEDGE_FILE,
    Config,
    build_system_prompt,
    load_project_instructions,
)
from .browser import BrowserManager
from .costs import Usage
from .journal import EditJournal
from .knowledge import KnowledgeStore
from .mcp import MCPManager
from .permissions import Decision, PermissionManager
from .shell import BackgroundManager, ShellSession
from .providers import Backend, StepResult, ToolCall, ToolResult
from .tools import Tool, ToolContext, ToolError, ToolOutput, build_registry, default_tools
from .tools.subagent import Crew, Task

MAX_STEPS = 60  # safety ceiling on tool-loop iterations per user turn

_GOAL_DIRECTIVE = (
    "You are now in AUTONOMOUS GOAL MODE. Work fully on your own to achieve the goal "
    "below using your tools. Make reasonable decisions without asking for confirmation "
    "on minor choices. Plan with todo_write, do the work, and VERIFY your result (run "
    "the code or its tests). Only when the goal is fully achieved AND verified, end your "
    "message with the exact token <<GOAL_ACHIEVED>>. If you are genuinely blocked and "
    "cannot proceed without the user, end with <<BLOCKED>> and explain why.\n\nGOAL: {goal}"
)

_COMPACT_SYSTEM = (
    "You compress a long conversation between a user and an autonomous agent into a "
    "compact briefing so the agent can continue seamlessly with far less context. "
    "Preserve the user's goals and requests, decisions made, key facts (file paths, "
    "names, commands and their results), what was just done, and any open tasks or "
    "next steps. Drop pleasantries and redundant detail. Write a tight briefing, not "
    "a dialogue."
)


def _ctx_tokens(usage) -> int:
    """Approximate input tokens carried into a request (the context size)."""
    return (
        (getattr(usage, "input_tokens", 0) or 0)
        + (getattr(usage, "cache_read_input_tokens", 0) or 0)
        + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
    )


_REFLECT_SYSTEM = (
    "You capture durable user preferences, stable facts, and reusable procedures "
    "from an AI agent's work session so the agent improves over time. You record "
    "clear user preferences readily, and skip transient, task-specific details. "
    "You output only a JSON array."
)

_REFLECT_INSTRUCTIONS = (
    "Review the exchange and decide what is worth remembering for FUTURE sessions.\n"
    "Capture, as separate items:\n"
    "- preference: anything the user said about how they want things done — their "
    "language, tone, tools, formatting, or standing instructions\n"
    "- fact: a stable detail about the user's machine, accounts, or projects\n"
    "- procedure: a concrete, reusable how-to you established\n"
    "Record clear user preferences even from a single sentence. Skip one-off task "
    "details and anything already obvious.\n"
    "Respond with ONLY a JSON array. Example:\n"
    '[{"kind":"preference","text":"Wants all answers in German"}]\n'
    "If truly nothing is worth saving, respond with []."
)


class Agent:
    def __init__(
        self,
        backend_factory: Callable[[], Backend],
        config: Config,
        console: Console | None = None,
    ):
        self.backend_factory = backend_factory
        self.backend: Backend = backend_factory()
        self.config = config
        self.console = console or ui.make_console()
        self.tools: list[Tool] = default_tools()
        self.mcp = MCPManager()
        if MCPManager.configured():
            self.mcp.connect_all()
            from .tools.mcp_tools import mcp_tools

            self.tools.extend(mcp_tools(self.mcp))
        self.registry = build_registry(self.tools)
        self.permissions = PermissionManager(self.console, yolo=config.yolo or config.auto)
        self.usage = Usage()
        self.knowledge = KnowledgeStore(KNOWLEDGE_FILE, embedder=self._make_embedder())
        self.project = load_project_instructions(Path.cwd())
        self.system = build_system_prompt(
            config, [e.text for e in self.knowledge.preferences()], self.project
        )
        self.shell = ShellSession(Path.cwd())
        self.background = BackgroundManager(CONFIG_DIR / "bg")
        self.journal = EditJournal()
        self.browser = BrowserManager(headless=config.browser_headless)
        self._last_ctx = 0  # approx input tokens of the last request, for compaction
        self._turn_memory = ""  # internal recalled facts/procedures for the active turn
        self.stream_view_factory = None  # optional callable(console, markdown, show_thinking) -> StreamSink
        self.ctx = ToolContext(
            cwd=Path.cwd(),
            console=self.console,
            permissions=self.permissions,
            config=config,
            knowledge=self.knowledge,
            shell=self.shell,
            background=self.background,
            journal=self.journal,
            browser=self.browser,
            spawn_subagent=self._run_subagent,
            spawn_crew=self._run_crew,
        )

    def _make_embedder(self):
        if not self.config.embed_model:
            return None
        from .embeddings import OllamaEmbedder

        if OllamaEmbedder.available(self.config.ollama_host, self.config.embed_model):
            return OllamaEmbedder(self.config.ollama_host, self.config.embed_model)
        return None

    @property
    def cost_model(self) -> str | None:
        return self.backend.cost_model

    def shutdown(self) -> None:
        """Tear down the shell session and any background processes."""
        try:
            self.shell.kill()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.background.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.browser.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.mcp.shutdown()
        except Exception:  # noqa: BLE001
            pass

    def refresh_system(self) -> None:
        """Rebuild the system prompt (e.g. after preferences/mode change)."""
        self.system = build_system_prompt(
            self.config, [e.text for e in self.knowledge.preferences()], self.project
        )

    def _tool_schemas(self) -> list[dict[str, Any]]:
        return [t.to_schema() for t in self.tools]

    # -- context compaction ------------------------------------------------

    def _compact_threshold(self) -> int:
        if self.config.compact_threshold > 0:
            return self.config.compact_threshold
        window = self.backend.context_window()
        if window:
            # Leave ~20% headroom for the response and the summary pass.
            return int(window * 0.8)
        return 5500 if self.config.is_local else 140000

    def _maybe_compact(self) -> None:
        """If the context has grown past the threshold, summarize the whole
        history into a compact briefing. Called at clean turn boundaries."""
        if not self.config.compact or self._last_ctx < self._compact_threshold():
            return
        transcript = self.backend.transcript_text().strip()
        if not transcript:
            return
        before = self._last_ctx
        try:
            sub = self.backend_factory()
            sub.add_user(transcript[:600_000] + "\n\nWrite the briefing now.")
            result = sub.generate(_COMPACT_SYSTEM, [], ui.NullView(), effort="low", think=False)
            self.usage.add(result.usage)
            summary = result.text.strip()
        except Exception:  # noqa: BLE001 — compaction must never break a turn
            return
        if summary:
            self.backend.reset_with_summary(summary)
            self._last_ctx = 0
            ui.render_compaction(self.console, before)

    # -- main turn ---------------------------------------------------------

    def run_turn(self, user_input: str) -> str:
        self._maybe_compact()
        recalled = self.knowledge.recall(
            user_input, k=self.config.recall_k, kinds=("fact", "procedure")
        )
        self._turn_memory = ""
        if recalled:
            ui.render_recall(self.console, len(recalled))
            self._turn_memory = "\n".join(f"- {e.text}" for e in recalled)

        if recalled and self.config.inject_recalled_memory:
            self.backend.add_user(f"<memory>\n{self._turn_memory}\n</memory>\n\n{user_input}")
        else:
            self.backend.add_user(user_input)
        try:
            text, tools_used = self._agent_loop()
        finally:
            self._turn_memory = ""
        self._reflect(user_input, [text] if text else [], tools_used)
        return text

    def _agent_loop(self) -> tuple[str, list[str]]:
        """Run the model→tools loop until the assistant stops calling tools.
        Returns the final assistant text and the list of tools used."""
        tools = self._tool_schemas()
        last_text = ""
        used: list[str] = []

        for _ in range(MAX_STEPS):
            view_factory = self.stream_view_factory or ui.StreamView
            with view_factory(
                self.console,
                markdown=self.config.stream_markdown,
                show_thinking=self.config.show_thinking,
            ) as view:
                system = self.system
                if getattr(self, "_turn_memory", ""):
                    system += (
                        "\n\n# Recalled relevant knowledge for this turn\n"
                        "Use this internal context when applicable, but do not "
                        "quote or display it unless it directly helps the user:\n"
                        + self._turn_memory
                    )
                result = self.backend.generate(system, tools, view)
            self.usage.add(result.usage)
            self._last_ctx = _ctx_tokens(result.usage)
            self.backend.add_assistant(result)
            if result.text:
                last_text = result.text
            used += [tc.name for tc in result.tool_calls]

            if result.stop_reason == "pause_turn":
                continue
            if not result.tool_calls:
                break

            results = [self._execute_tool(tc) for tc in result.tool_calls]
            self.backend.add_tool_results(results)
        else:
            self.console.print("[yellow]Reached the step limit for this turn.[/]")
        return last_text, used

    # -- autonomous goal mode ---------------------------------------------

    def run_goal(self, goal: str, max_rounds: int = 10) -> None:
        """Work autonomously toward a goal: act, self-verify, and keep going
        across rounds until the goal is achieved, blocked, or rounds run out."""
        ui.render_goal_header(self.console, goal)
        recalled = self.knowledge.recall(goal, k=self.config.recall_k, kinds=("fact", "procedure"))
        self._turn_memory = ""
        if recalled:
            ui.render_recall(self.console, len(recalled))
            self._turn_memory = "\n".join(f"- {e.text}" for e in recalled)
        message = _GOAL_DIRECTIVE.format(goal=goal)
        all_tools: list[str] = []
        outcome = "incomplete"

        for rnd in range(1, max_rounds + 1):
            ui.render_round(self.console, rnd, max_rounds)
            self._maybe_compact()
            self.backend.add_user(message)
            text, used = self._agent_loop()
            all_tools += used
            upper = text.upper()
            if "<<GOAL_ACHIEVED>>" in upper:
                outcome = "achieved"
                break
            if "<<BLOCKED>>" in upper:
                outcome = "blocked"
                break
            message = (
                "You have NOT emitted <<GOAL_ACHIEVED>> yet. Verify what remains for the "
                f"goal — '{goal}' — then keep working until it is fully done and verified "
                "(run it or its tests). Emit <<GOAL_ACHIEVED>> when truly complete, or "
                "<<BLOCKED>> with a reason if you cannot proceed without the user."
            )
        self._turn_memory = ""
        ui.render_goal_result(self.console, outcome)
        self._reflect(f"[goal] {goal}", [], all_tools)

    # -- tool execution ----------------------------------------------------

    def _execute_tool(self, tc: ToolCall) -> ToolResult:
        tool = self.registry.get(tc.name)
        if tool is None:
            ui.render_tool_call(self.console, tc.name, "(unknown tool)")
            return ToolResult(tc.id, tc.name, f"Unknown tool: {tc.name}", is_error=True)

        ui.render_tool_call(self.console, tc.name, tool.call_summary(tc.input))

        if tool.requires_permission:
            preview = tool.permission_preview(tc.input, self.ctx)
            if self.permissions.request(tc.name, tc.name, preview) is Decision.DENY:
                ui.render_tool_denied(self.console, tc.name)
                return ToolResult(
                    tc.id, tc.name,
                    "User denied this action. Adjust your approach or ask the user.",
                    is_error=True,
                )

        try:
            output = tool.run(tc.input, self.ctx)
        except ToolError as e:
            ui.render_tool_result(self.console, str(e), is_error=True)
            return ToolResult(tc.id, tc.name, str(e), is_error=True)
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            ui.render_tool_result(self.console, msg, is_error=True)
            return ToolResult(tc.id, tc.name, msg, is_error=True)

        text, images = (output.text, output.images) if isinstance(output, ToolOutput) else (output, [])
        if tc.name != "todo_write":  # todo_write renders its own panel
            shown = text + (f"  ⟨+{len(images)} image⟩" if images else "")
            ui.render_tool_result(self.console, shown)
        return ToolResult(tc.id, tc.name, text, images=images)

    # -- continuous learning ----------------------------------------------

    def _reflect(self, user_input: str, texts: list[str], tools: list[str]) -> None:
        """After a turn, extract durable knowledge and store it. Best-effort —
        a failure here must never break the conversation."""
        if not self.config.learning:
            return
        outcome = texts[-1] if texts else ""
        if not tools and len(outcome) < 40:  # skip trivial turns
            return

        used = ", ".join(dict.fromkeys(tools)) or "none"
        transcript = (
            f"User request: {user_input.strip()[:500]}\n"
            f"Tools used: {used}\n"
            f"Assistant outcome: {outcome.strip()[:900]}\n\n{_REFLECT_INSTRUCTIONS}"
        )
        try:
            sub = self.backend_factory()
            sub.add_user(transcript)
            result = sub.generate(_REFLECT_SYSTEM, [], ui.NullView(), effort="low", think=False)
            self.usage.add(result.usage)
            learned = self._store_lessons(result.text)
        except Exception:  # noqa: BLE001
            return

        if learned:
            self.refresh_system()  # surface new preferences on the next turn
            for kind, text in learned:
                ui.render_learned(self.console, kind, text)

    def _store_lessons(self, raw: str) -> list[tuple[str, str]]:
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []
        try:
            items = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
        learned: list[tuple[str, str]] = []
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            text = str(it.get("text", "")).strip()
            kind = str(it.get("kind", "fact")).strip()
            if not text:
                continue
            entry = self.knowledge.add(kind, text)
            if entry is not None:
                learned.append((entry.kind, entry.text))
        return learned

    # -- sub-agents / crews ------------------------------------------------

    def _subagent_tools(self) -> list[Tool]:
        """Tools exposed to nested agents.

        Nested agents may use normal local tools, but they cannot recursively spawn
        `task` or `crew` calls. This keeps orchestration bounded and avoids runaway
        agent trees.
        """
        return [t for t in self.tools if not isinstance(t, (Task, Crew))]

    def _run_subagent(self, instructions: str, max_steps: int) -> str:
        return self._run_specialist(
            role="sub-agent",
            title="Focused delegated task",
            instructions=instructions,
            max_steps=max_steps,
        )

    def _run_specialist(self, role: str, title: str, instructions: str, max_steps: int) -> str:
        sub = self.backend_factory()
        sub_tools = self._subagent_tools()
        sub_registry = build_registry(sub_tools)
        schemas = [t.to_schema() for t in sub_tools]
        sub_system = (
            f"You are Zuse's {role} specialist. Complete exactly one assigned task. "
            "Use tools when useful, keep changes focused, verify your own claims when "
            "possible, and finish with a concise report containing: summary, files or "
            "commands inspected/changed, verification performed, and blockers. You cannot "
            "ask the user questions."
        )
        sub.add_user(f"# Task: {title}\n\n{instructions}")
        view = ui.NullView()
        final_text = ""

        with self.console.status(f"[magenta]{role} working…[/]", spinner="dots"):
            for _ in range(max(1, max_steps)):
                result: StepResult = sub.generate(sub_system, schemas, view, effort="medium")
                self.usage.add(result.usage)
                sub.add_assistant(result)
                if result.text:
                    final_text = result.text
                if result.stop_reason == "pause_turn":
                    continue
                if not result.tool_calls:
                    break
                results = []
                for tc in result.tool_calls:
                    tool = sub_registry.get(tc.name)
                    if tool is None:
                        results.append(ToolResult(tc.id, tc.name, f"Unknown tool: {tc.name}", True))
                        continue
                    try:
                        out = tool.run(tc.input, self.ctx)
                        text, images = (out.text, out.images) if isinstance(out, ToolOutput) else (out, [])
                        results.append(ToolResult(tc.id, tc.name, text, images=images))
                    except Exception as e:  # noqa: BLE001
                        results.append(ToolResult(tc.id, tc.name, str(e), True))
                sub.add_tool_results(results)

        return final_text or f"({role} returned no text)"

    def _default_crew_tasks(self, goal: str, mode: str, max_steps: int) -> list[dict[str, Any]]:
        if mode == "research":
            return [
                {
                    "role": "researcher",
                    "title": "Map relevant code and constraints",
                    "instructions": f"Research this goal without editing files: {goal}",
                    "max_steps": max_steps,
                },
                {
                    "role": "reviewer",
                    "title": "Review risks and propose implementation plan",
                    "instructions": f"Review the goal and produce a concise execution plan: {goal}",
                    "max_steps": max(4, max_steps // 2),
                },
            ]
        if mode == "review":
            return [
                {
                    "role": "reviewer",
                    "title": "Review current changes",
                    "instructions": f"Review the repository changes and risks for this goal: {goal}",
                    "max_steps": max_steps,
                },
                {
                    "role": "tester",
                    "title": "Suggest or run verification",
                    "instructions": f"Find and, if safe, run focused verification for: {goal}",
                    "max_steps": max_steps,
                },
            ]
        return [
            {
                "role": "planner",
                "title": "Break down the goal",
                "instructions": f"Create a short implementation plan for this goal: {goal}",
                "max_steps": max(4, max_steps // 2),
            },
            {
                "role": "researcher",
                "title": "Inspect relevant code",
                "instructions": f"Inspect the codebase for files and conventions relevant to: {goal}",
                "max_steps": max_steps,
            },
            {
                "role": "tester",
                "title": "Identify verification path",
                "instructions": f"Find the most relevant tests/checks for this goal and report how to verify it: {goal}",
                "max_steps": max(4, max_steps // 2),
            },
        ]

    def _normalize_crew_tasks(
        self, goal: str, tasks: list[dict[str, Any]], mode: str, max_steps: int
    ) -> list[dict[str, Any]]:
        if not tasks:
            return self._default_crew_tasks(goal, mode, max_steps)
        normalized = []
        for i, raw in enumerate(tasks, start=1):
            if not isinstance(raw, dict):
                continue
            role = str(raw.get("role") or f"agent-{i}").strip()
            title = str(raw.get("title") or role).strip()
            instructions = str(raw.get("instructions") or "").strip()
            if not instructions:
                instructions = f"Work on this part of the goal: {goal}"
            try:
                steps = int(raw.get("max_steps", max_steps))
            except (TypeError, ValueError):
                steps = max_steps
            normalized.append({"role": role, "title": title, "instructions": instructions, "max_steps": steps})
        return normalized or self._default_crew_tasks(goal, mode, max_steps)

    def _run_crew(
        self, goal: str, tasks: list[dict[str, Any]], mode: str = "auto", max_steps: int = 10
    ) -> str:
        plan = self._normalize_crew_tasks(goal, tasks, mode, max_steps)
        reports: list[str] = []
        self.console.print(f"[magenta]crew:[/] {len(plan)} specialist(s) for {goal[:90]}")
        for i, task in enumerate(plan, start=1):
            role = str(task["role"])
            title = str(task["title"])
            self.console.print(f"  [cyan]{i}. {role}[/] — {title}")
            report = self._run_specialist(
                role=role,
                title=title,
                instructions=str(task["instructions"]),
                max_steps=int(task["max_steps"]),
            )
            reports.append(f"## {i}. {role}: {title}\n{report.strip()}")

        synthesis = (
            "You are Zuse's crew coordinator. Synthesize the specialist reports into "
            "one concise handoff for the main agent. Include: overall status, key "
            "findings, changes made, verification/results, blockers, and recommended "
            "next actions. Do not invent work that the reports do not support."
        )
        sub = self.backend_factory()
        sub.add_user(f"# Goal\n{goal}\n\n# Specialist reports\n\n" + "\n\n".join(reports))
        try:
            result = sub.generate(synthesis, [], ui.NullView(), effort="low", think=False)
            self.usage.add(result.usage)
            summary = result.text.strip()
        except Exception:  # noqa: BLE001
            summary = "\n\n".join(reports)
        return summary or "\n\n".join(reports) or "(crew returned no reports)"
