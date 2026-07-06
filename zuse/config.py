"""Configuration, constants, pricing, and paths for Zuse."""

from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

# --- Model defaults -------------------------------------------------------

DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_EFFORT = "high"          # low | medium | high | xhigh | max
DEFAULT_MAX_TOKENS = 32000       # streaming, so high ceiling is fine
DEFAULT_THINKING = True          # adaptive thinking on by default

# Per-1M-token USD pricing for cost estimation. Cache write = 1.25x input,
# cache read = 0.1x input.
PRICING: dict[str, dict[str, float]] = {
    "claude-fable-5":      {"input": 10.0, "output": 50.0},
    "claude-opus-4-8":     {"input": 5.0,  "output": 25.0},
    "claude-opus-4-7":     {"input": 5.0,  "output": 25.0},
    "claude-opus-4-6":     {"input": 5.0,  "output": 25.0},
    "claude-sonnet-4-6":   {"input": 3.0,  "output": 15.0},
    "claude-haiku-4-5":    {"input": 1.0,  "output": 5.0},
}

MODEL_ALIASES = {
    "fable": "claude-fable-5",
    "opus": "claude-opus-4-8",
    "opus-4.8": "claude-opus-4-8",
    "opus-4.7": "claude-opus-4-7",
    "opus-4.6": "claude-opus-4-6",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5",
}

# --- Paths ----------------------------------------------------------------

CONFIG_DIR = Path(os.environ.get("ZUSE_HOME", Path.home() / ".zuse"))
SESSIONS_DIR = CONFIG_DIR / "sessions"
MEMORY_FILE = CONFIG_DIR / "memory.md"
KNOWLEDGE_FILE = CONFIG_DIR / "knowledge.jsonl"
CONFIG_FILE = CONFIG_DIR / "config.json"
DREAMS_FILE = CONFIG_DIR / "dreams.jsonl"
IMPROVEMENTS_FILE = CONFIG_DIR / "improvements.md"


def ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def resolve_model(name: str | None) -> str:
    if not name:
        return DEFAULT_MODEL
    return MODEL_ALIASES.get(name.lower(), name)


PROJECT_FILES = ("AGENTS.md", ".zuse.md", "ZUSE.md")


def load_project_instructions(cwd: Path | None = None) -> str:
    """Find a project instruction file in cwd or any parent (up to home/root)
    and return its contents. Lets each project teach Zuse its own conventions."""
    cwd = (cwd or Path.cwd()).resolve()
    home = Path.home().resolve()
    for d in [cwd, *cwd.parents]:
        for name in PROJECT_FILES:
            f = d / name
            if f.is_file():
                try:
                    return f.read_text(errors="replace").strip()
                except OSError:
                    return ""
        if d == home or (d / ".git").exists():
            break  # don't walk above the home dir or out of the project/repo
    return ""


@dataclass
class Config:
    """User-tunable runtime configuration, persisted to ~/.zuse/config.json."""

    provider: str = "anthropic"      # "anthropic" | "ollama" | "openai" | "codex"
    model: str = DEFAULT_MODEL       # Anthropic model id
    local_model: str = "qwen2.5"     # Ollama model tag (auto-detected if absent)
    ollama_host: str = "http://localhost:11434"
    openai_model: str = "gpt-4o-mini"               # OpenAI / OpenAI-compatible model
    openai_base_url: str = "https://api.openai.com/v1"
    codex_model: str = "gpt-5.5"      # model for the Codex "Sign in with ChatGPT" path
    effort: str = DEFAULT_EFFORT
    max_tokens: int = DEFAULT_MAX_TOKENS
    thinking: bool = DEFAULT_THINKING
    show_thinking: bool = True
    enable_web: bool = True          # server-side web_search + web_fetch tools (Anthropic only)
    yolo: bool = False               # auto-approve all permission prompts
    auto: bool = False               # autonomous mode: auto-approve + decisive directive
    stream_markdown: bool = True     # live markdown rendering while streaming
    persona: str = ""                # extra system-prompt instructions
    learning: bool = True            # reflect after each turn and grow knowledge
    embed_model: str = ""            # optional Ollama embedding model for semantic recall
    recall_k: int = 6                # how many memories to recall per turn
    inject_recalled_memory: bool = False  # keep recall internal; don't add <memory> blocks to chat
    compact: bool = True             # auto-summarize history when context grows large
    compact_threshold: int = 0       # input-token trigger (0 = auto per provider)
    browser_headless: bool = True    # run the automation browser without a visible window
    crew_concurrency: int = 4        # max specialist sub-agents running in parallel per crew
    crew_planner: bool = True        # let a coordinator agent decompose goals into specialists
    auto_crew: bool = True           # auto-route substantial tasks to a crew (no /crew needed)
    show_actions: bool = True        # show tool calls/output + live stream; off = only agent progress
    dream_enabled: bool = True       # background idle reflection + memory maintenance
    dream_interval_minutes: int = 45
    dream_idle_delay_seconds: int = 120
    dream_recent_sessions: int = 5
    dream_model_reflection: bool = True  # call a low-effort model for dream insights

    @property
    def is_local(self) -> bool:
        return self.provider == "ollama"

    @property
    def active_model(self) -> str:
        return {
            "ollama": self.local_model,
            "openai": self.openai_model,
            "codex": self.codex_model,
        }.get(self.provider, self.model)

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text())
                for k, v in data.items():
                    if hasattr(cfg, k):
                        setattr(cfg, k, v)
            except (json.JSONDecodeError, OSError):
                pass
        # Environment overrides
        if env_model := os.environ.get("ZUSE_MODEL"):
            cfg.model = resolve_model(env_model)
        if env_host := os.environ.get("OLLAMA_HOST"):
            cfg.ollama_host = env_host if env_host.startswith("http") else f"http://{env_host}"
        return cfg

    def save(self) -> None:
        ensure_dirs()
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2))


def build_system_prompt(
    cfg: Config, preferences: list[str] | None = None, project: str = ""
) -> str:
    """Assemble the agent's system prompt. Kept byte-stable except for the
    preference/persona sections so the cached prefix stays valid across turns."""
    cwd = Path.cwd()
    today = datetime.now().strftime("%Y-%m-%d")
    sysinfo = f"{platform.system()} {platform.release()} ({platform.machine()})"
    is_mac = platform.system() == "Darwin"

    base = f"""You are Zuse, an autonomous AI agent that runs in the user's terminal and \
acts on their behalf. You have real access to their computer through tools — \
shell, file editing, code execution{', full macOS control,' if is_mac else ''} \
and web access — and you complete tasks end to end rather than just describing how.

# Operating principles
- Bias toward action. When a request is clear, use your tools to accomplish it \
instead of explaining what the user could do. Read files before editing them.
- Work in small, verifiable steps. After changing code, run it or its tests to \
confirm the change works. Report failures honestly with the actual output.
- Be precise and concise in prose. Lead with the outcome. The user reads your \
final message, not your tool logs — summarize what you actually did there.
- For multi-step tasks, maintain a plan with the `todo_write` tool so the user \
can follow your progress. Update statuses as you go.
- For a large task that splits into independent parts, delegate to a `crew` of \
parallel specialist sub-agents (or a single `task` sub-agent for one focused \
piece). They work concurrently and the user watches their live progress.
- Prefer dedicated tools (read_file, edit_file, grep, glob) over equivalent \
shell commands; they are safer and clearer.
- Destructive or outward-facing actions may require user confirmation. Don't try \
to work around a denied action — adapt.
- When you genuinely need information from the user to proceed, ask. Otherwise, \
make a reasonable decision, note it, and continue."""

    if is_mac:
        base += """

# macOS access
You can control this Mac directly:
- `applescript` — automate any app and the system (Finder, Safari, Mail, Notes, \
Music, Calendar, Reminders, System Events for keystrokes/clicks). Most powerful.
- `open` — open files, folders, URLs, or launch apps.
- `clipboard_read` / `clipboard_write` — read and set the clipboard.
- `screenshot` — capture the screen to a file.
- `notify` — show a notification banner.
- `system_info` — version, hardware, disk, uptime.
Use these to genuinely operate the machine, not just suggest steps."""

    base += """

# Continuous learning
You improve over time by using persisted knowledge from earlier sessions. User \
preferences are included as standing instructions in this system prompt. Other \
relevant facts and procedures may be recalled internally for each task; use them \
when applicable, but don't repeat them to the user unless useful. \
Whenever the user states a preference, gives you a standing instruction, or asks \
you to remember something, call the `remember` tool right away — actually invoke \
it, don't just acknowledge it in words. Also save durable facts about their \
machine/projects and reusable procedures you work out."""

    if cfg.auto:
        base += """

# Auto mode (ACTIVE)
You are running in autonomous auto mode. Drive the task to full completion on your
own without stopping for confirmation on routine or minor decisions — naming,
formatting, reasonable defaults, and obvious next steps are yours to make (note
them briefly rather than asking). Chain the tool calls needed, and verify your work
(run the code or its tests) before reporting that you're done. Only pause to ask the
user when a choice is genuinely consequential, ambiguous, or destructive in a way
you should not decide alone. Keep going until the request is actually finished."""

    base += f"""

# Environment
- Working directory: {cwd}
- Operating system: {sysinfo}
- Today's date: {today}

# Style
- Reference files as clickable paths like path/to/file.py:42.
- Format code, commands, and identifiers in backticks.
- Keep responses scannable. Use short paragraphs and lists where they help."""

    if project.strip():
        base += (
            "\n\n# Project instructions\n"
            "From this project's instruction file — follow these conventions for "
            "work in this project:\n\n" + project.strip()
        )

    if cfg.persona.strip():
        base += f"\n\n# Additional instructions\n{cfg.persona.strip()}"

    prefs = [p for p in (preferences or []) if p.strip()]
    if prefs:
        base += (
            "\n\n# Standing instructions from the user (highest priority)\n"
            "These are durable preferences the user has set in earlier sessions. "
            "Follow every one of them in ALL of your responses, even when the "
            "current message doesn't repeat them and regardless of the language the "
            "user writes in:\n" + "\n".join(f"- {p}" for p in prefs)
        )

    return base
