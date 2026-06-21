"""Core agentic loop: provider-neutral, with tool execution, sub-agents, and a
continuous-learning knowledge store (recall before each task, reflect after)."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from rich.console import Console

from . import ui
from .agentpool import AgentRegistry
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
        self.crew_observer = None  # optional callable(event, payload) for WebUI/live views
        # Auto-approving permissions for crew specialists (built lazily). Crews
        # run autonomously, so their tools never prompt on stdin — which would
        # collide with the live dashboard and across parallel threads.
        self._crew_permissions: PermissionManager | None = None
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

        auto_crew = self._should_auto_crew(user_input)

        if recalled and self.config.inject_recalled_memory:
            self.backend.add_user(f"<memory>\n{self._turn_memory}\n</memory>\n\n{user_input}")
        else:
            self.backend.add_user(user_input)
        try:
            if auto_crew:
                text, tools_used = self._auto_crew_turn(user_input), ["crew"]
            else:
                text, tools_used = self._agent_loop()
        finally:
            self._turn_memory = ""
        self._reflect(user_input, [text] if text else [], tools_used)
        return text

    def _turn_system(self) -> str:
        """System prompt for the active turn, plus any recalled knowledge."""
        system = self.system
        if getattr(self, "_turn_memory", ""):
            system += (
                "\n\n# Recalled relevant knowledge for this turn\n"
                "Use this internal context when applicable, but do not "
                "quote or display it unless it directly helps the user:\n"
                + self._turn_memory
            )
        return system

    def _generate_step(self, tools: list[dict[str, Any]], step: int):
        """One model call. In normal mode it streams live; in quiet mode
        (config.show_actions = False) it runs silently behind a compact
        'which agent is running and how far' progress line instead."""
        if self.config.show_actions:
            view_factory = self.stream_view_factory or ui.StreamView
            with view_factory(
                self.console,
                markdown=self.config.stream_markdown,
                show_thinking=self.config.show_thinking,
            ) as view:
                return self.backend.generate(self._turn_system(), tools, view)
        with ui.TurnProgress(self.console, self.ctx.todos, step=step):
            return self.backend.generate(self._turn_system(), tools, ui.NullView())

    def _agent_loop(self) -> tuple[str, list[str]]:
        """Run the model→tools loop until the assistant stops calling tools.
        Returns the final assistant text and the list of tools used."""
        tools = self._tool_schemas()
        last_text = ""
        used: list[str] = []

        for step in range(1, MAX_STEPS + 1):
            result = self._generate_step(tools, step)
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

            results: list[ToolResult] = []
            try:
                for tc in result.tool_calls:
                    results.append(self._execute_tool(tc))
            except KeyboardInterrupt:
                # Record an output for every call so history stays balanced —
                # the backends reject an unanswered tool call on the next turn.
                done = {r.tool_call_id for r in results}
                for tc in result.tool_calls:
                    if tc.id not in done:
                        results.append(ToolResult(
                            tc.id, tc.name, "Interrupted by the user.", is_error=True))
                self.backend.add_tool_results(results)
                raise
            self.backend.add_tool_results(results)
        else:
            self.console.print("[yellow]Reached the step limit for this turn.[/]")

        # Quiet mode streamed nothing live, so print the final answer once.
        if not self.config.show_actions and last_text:
            ui.render_answer(self.console, last_text)
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

    def run_crew(self, goal: str) -> None:
        """Explicitly launch a crew of parallel specialist sub-agents for a goal
        and show the live dashboard (the `/crew` command). The coordinator plans
        the specialists; their synthesized report is printed when they finish."""
        report = self._run_crew(goal, [], mode="auto", max_steps=10)
        ui.render_answer(self.console, report)

    # -- tool execution ----------------------------------------------------

    def _execute_tool(self, tc: ToolCall) -> ToolResult:
        # Quiet mode (show_actions = False) hides the per-tool call/output log;
        # the user sees only the agent-progress line and crew dashboards.
        show = self.config.show_actions
        tool = self.registry.get(tc.name)
        if tool is None:
            if show:
                ui.render_tool_call(self.console, tc.name, "(unknown tool)")
            return ToolResult(tc.id, tc.name, f"Unknown tool: {tc.name}", is_error=True)

        if show:
            ui.render_tool_call(self.console, tc.name, tool.call_summary(tc.input))

        if tool.requires_permission:
            preview = tool.permission_preview(tc.input, self.ctx)
            if self.permissions.request(tc.name, tc.name, preview) is Decision.DENY:
                if show:
                    ui.render_tool_denied(self.console, tc.name)
                return ToolResult(
                    tc.id, tc.name,
                    "User denied this action. Adjust your approach or ask the user.",
                    is_error=True,
                )

        try:
            output = self._run_tool_watched(tool, tc, show)
        except ToolError as e:
            if show:
                ui.render_tool_result(self.console, str(e), is_error=True)
            return ToolResult(tc.id, tc.name, str(e), is_error=True)
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            if show:
                ui.render_tool_result(self.console, msg, is_error=True)
            return ToolResult(tc.id, tc.name, msg, is_error=True)

        text, images = (output.text, output.images) if isinstance(output, ToolOutput) else (output, [])
        if show and tc.name != "todo_write":  # todo_write renders its own panel
            shown = text + (f"  ⟨+{len(images)} image⟩" if images else "")
            ui.render_tool_result(self.console, shown)
        return ToolResult(tc.id, tc.name, text, images=images)

    def _run_tool_watched(self, tool: Tool, tc: ToolCall, show: bool):
        """Run a tool. In quiet mode, show a live spinner naming the running
        tool so a slow tool (e.g. a long shell command) reads as 'working',
        not a hang. Skipped for crew/task, which render their own live views,
        and in verbose mode, which already logs the call."""
        if show or tc.name in ("crew", "task"):
            return tool.run(tc.input, self.ctx)
        summary = tool.call_summary(tc.input)
        label = f"[#22D3EE]{tc.name}[/] [grey42]{summary}[/]" if summary else f"[#22D3EE]{tc.name}[/]"
        with self.console.status(label, spinner="dots"):
            return tool.run(tc.input, self.ctx)

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

    def _specialist_ctx(self) -> ToolContext:
        """An isolated tool context for a crew specialist: its own shell session
        and todo list (so parallel agents don't interleave shell state), auto-
        approving permissions, and no ability to spawn further agents (two-level
        cap). Knowledge/background/journal/browser are shared (all guarded)."""
        if self._crew_permissions is None:
            self._crew_permissions = PermissionManager(self.console, yolo=True)
        return ToolContext(
            cwd=self.ctx.cwd,
            console=self.console,
            permissions=self._crew_permissions,
            config=self.config,
            todos=[],
            knowledge=self.knowledge,
            shell=ShellSession(self.ctx.cwd),
            background=self.background,
            journal=self.journal,
            browser=self.browser,
            spawn_subagent=None,
            spawn_crew=None,
        )

    def _run_subagent(self, instructions: str, max_steps: int) -> str:
        """The `task` tool: one focused sub-agent, run inline (not in a crew).
        Uses an isolated auto-approving context like crew specialists, so it
        never blocks on a permission prompt behind its status spinner."""
        ctx = self._specialist_ctx()
        try:
            with self.console.status("[magenta]sub-agent working…[/]", spinner="dots"):
                return self._agent_subloop(
                    "sub-agent", "Focused delegated task", instructions, max_steps, ctx
                )
        finally:
            try:
                ctx.shell.kill()
            except Exception:  # noqa: BLE001
                pass

    def _run_specialist(
        self,
        rid: str,
        registry: AgentRegistry,
        role: str,
        title: str,
        instructions: str,
        max_steps: int,
    ) -> str:
        """Run one crew specialist in its own isolated context, reporting live
        progress into `registry`. Never raises — a failing specialist is recorded
        and returns an error report so it can't take down the rest of the crew."""
        registry.start(rid)
        ctx = self._specialist_ctx()
        try:
            text = self._agent_subloop(role, title, instructions, max_steps, ctx, registry, rid)
            registry.finish(rid, ok=True)
            return text
        except Exception as e:  # noqa: BLE001
            registry.finish(rid, ok=False, error=str(e))
            return f"({role} failed: {e})"
        finally:
            try:
                ctx.shell.kill()
            except Exception:  # noqa: BLE001
                pass

    def _agent_subloop(
        self,
        role: str,
        title: str,
        instructions: str,
        max_steps: int,
        ctx: ToolContext,
        registry: AgentRegistry | None = None,
        rid: str | None = None,
    ) -> str:
        """Shared nested agent loop used by both `task` and crew specialists.

        Runs a fresh backend's tool loop against `ctx`. When a `registry`/`rid`
        are given, reports step count, current activity, and todo progress so the
        crew dashboard can show how far along the agent is."""
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

        for step in range(1, max(1, max_steps) + 1):
            if registry is not None:
                registry.update(rid, step=step, activity="thinking…")
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
                if registry is not None:
                    registry.update(rid, activity=f"{tc.name} · {tool.call_summary(tc.input)}")
                try:
                    out = tool.run(tc.input, ctx)
                    text, images = (out.text, out.images) if isinstance(out, ToolOutput) else (out, [])
                    results.append(ToolResult(tc.id, tc.name, text, images=images))
                except Exception as e:  # noqa: BLE001
                    results.append(ToolResult(tc.id, tc.name, str(e), True))
            sub.add_tool_results(results)
            if registry is not None:
                done = sum(1 for t in ctx.todos if t.status == "done")
                registry.update(rid, todos_done=done, todos_total=len(ctx.todos))

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

    def _plan_crew(self, goal: str, mode: str, max_steps: int) -> list[dict[str, Any]]:
        """Coordinator step: let an agent decompose the goal into 3–6 parallel
        specialists. Falls back to the static plan when disabled or on failure."""
        if not getattr(self.config, "crew_planner", True):
            return self._default_crew_tasks(goal, mode, max_steps)
        planner_system = (
            "You are Zuse's crew coordinator. Decompose the goal into a small team of "
            "specialist sub-agents that can work IN PARALLEL. Pick 3–6 specialists with "
            "distinct roles (e.g. planner, researcher, coder, tester, reviewer, docs). "
            "Each gets standalone instructions — they do not share context or talk to "
            "each other, so make each task self-contained. Respond with ONLY a JSON array "
            "of objects with keys: role, title, instructions."
        )
        sub = self.backend_factory()
        sub.add_user(f"Goal: {goal}\nMode: {mode}\n\nReturn 3-6 specialists as a JSON array.")
        try:
            with self.console.status("[magenta]coordinator planning the crew…[/]", spinner="dots"):
                result = sub.generate(planner_system, [], ui.NullView(), effort="low", think=False)
            self.usage.add(result.usage)
            planned = self._parse_crew_plan(result.text, goal, max_steps)
        except Exception:  # noqa: BLE001
            planned = []
        return planned or self._default_crew_tasks(goal, mode, max_steps)

    def _parse_crew_plan(self, raw: str, goal: str, max_steps: int) -> list[dict[str, Any]]:
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []
        try:
            items = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
        plan: list[dict[str, Any]] = []
        for i, raw_task in enumerate(items if isinstance(items, list) else [], start=1):
            if not isinstance(raw_task, dict):
                continue
            role = str(raw_task.get("role") or f"agent-{i}").strip()
            title = str(raw_task.get("title") or role).strip()
            instructions = str(raw_task.get("instructions") or "").strip()
            if not instructions:
                instructions = f"Work on this part of the goal: {goal}"
            plan.append(
                {"role": role, "title": title, "instructions": instructions, "max_steps": max_steps}
            )
            if len(plan) >= 6:  # cap the fan-out
                break
        return plan

    def _normalize_crew_tasks(
        self, goal: str, tasks: list[dict[str, Any]], mode: str, max_steps: int
    ) -> list[dict[str, Any]]:
        if not tasks:
            return self._plan_crew(goal, mode, max_steps)
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

    def _run_specialists(self, goal: str, plan: list[dict[str, Any]]) -> list[str]:
        """Run a planned crew of specialists in parallel under the live dashboard,
        returning their reports in plan order. Shared by the `crew` tool, the
        `/crew` command, and automatic crew dispatch."""
        crew_observer = getattr(self, "crew_observer", None)
        registry = AgentRegistry(on_change=crew_observer)
        if crew_observer:
            crew_observer("crew_start", {"goal": goal, "agents": []})
        runs = [
            (registry.create(str(t["role"]), str(t["title"]), int(t["max_steps"])), t)
            for t in plan
        ]
        reports: list[str] = [""] * len(runs)
        concurrency = max(1, int(getattr(self.config, "crew_concurrency", 4)))

        with ui.CrewDashboard(self.console, registry, goal):
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                future_to_idx = {
                    pool.submit(
                        self._run_specialist,
                        rid,
                        registry,
                        str(task["role"]),
                        str(task["title"]),
                        str(task["instructions"]),
                        int(task["max_steps"]),
                    ): idx
                    for idx, (rid, task) in enumerate(runs)
                }
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    task = runs[idx][1]
                    report = future.result()  # never raises; specialist captures errors
                    reports[idx] = f"## {idx + 1}. {task['role']}: {task['title']}\n{report.strip()}"
        if crew_observer:
            crew_observer("crew_done", {"goal": goal, "agents": [r.__dict__ for r in registry.snapshot()]})
        return reports

    def _run_crew(
        self, goal: str, tasks: list[dict[str, Any]], mode: str = "auto", max_steps: int = 10
    ) -> str:
        plan = self._normalize_crew_tasks(goal, tasks, mode, max_steps)
        reports = self._run_specialists(goal, plan)
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

    # -- automatic crew routing -------------------------------------------

    def _should_auto_crew(self, user_input: str) -> bool:
        """Decide whether a turn should automatically run as a crew, so the user
        never has to type /crew. Cheap classifier: a quick low-effort call that
        answers crew/solo, gated by a length heuristic to skip trivial messages.
        Conservative by design — a crew costs many sub-agent calls."""
        if not getattr(self.config, "auto_crew", False):
            return False
        if len(user_input.split()) < 4:  # greetings / quick acks stay solo
            return False
        router_system = (
            "You route a user's request to either a single agent or a crew of parallel "
            "specialist sub-agents. Answer 'crew' ONLY for a substantial task with several "
            "independent parts that genuinely benefit from parallel specialists — e.g. a "
            "multi-file feature, a broad investigation or audit, or research + implement + "
            "test. Answer 'solo' for anything quick, conversational, exploratory, or "
            "single-file. When unsure, answer 'solo'. Respond with ONLY 'crew' or 'solo'."
        )
        sub = self.backend_factory()
        sub.add_user(f"Request: {user_input}\n\nAnswer with one word: crew or solo.")
        try:
            with self.console.status("[magenta]routing…[/]", spinner="dots"):
                result = sub.generate(router_system, [], ui.NullView(), effort="low", think=False)
            self.usage.add(result.usage)
        except Exception:  # noqa: BLE001
            return False
        return result.text.strip().lower().startswith("crew")

    def _auto_crew_turn(self, goal: str) -> str:
        """Run a turn as a crew: specialists work in parallel (live dashboard),
        then the MAIN backend synthesizes the final answer — a real assistant turn,
        so history stays valid and follow-ups have the result in context."""
        self.console.print(
            "[#8B5CF6]⛓ delegating to a crew of sub-agents…[/] "
            "[grey42](/autocrew to turn this off)[/]"
        )
        plan = self._normalize_crew_tasks(goal, [], "auto", 10)
        reports = self._run_specialists(goal, plan)
        system = self._turn_system() + (
            "\n\n# Crew specialist reports\n"
            "A crew of sub-agents just did this work in parallel. Write the final answer "
            "for the user from their reports — summarize what was done, results, and any "
            "blockers or next steps. Do not redo their work.\n\n" + "\n\n".join(reports)
        )
        if self.config.show_actions:
            with ui.StreamView(
                self.console,
                markdown=self.config.stream_markdown,
                show_thinking=self.config.show_thinking,
            ) as view:
                result = self.backend.generate(system, [], view)
        else:
            result = self.backend.generate(system, [], ui.NullView())
        self.usage.add(result.usage)
        self._last_ctx = _ctx_tokens(result.usage)
        self.backend.add_assistant(result)
        if not self.config.show_actions and result.text:
            ui.render_answer(self.console, result.text)
        return result.text
