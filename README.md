# Zuse

<p align="center">
  <img src="assets/zuse-logo.png" alt="Zuse logo" width="420">
</p>

An autonomous terminal AI agent — in the spirit of agents like OpenClaw and
Hermes. Zuse completes tasks end to end: it reads and edits files, runs shell
commands and Python, searches the web, plans with a todo list, spawns sub-agents,
and remembers things across sessions.

**Runs locally by default.** With no API key set, Zuse uses a local model via
[Ollama](https://ollama.com) — fully offline and free. It also speaks to Claude
(Anthropic), any OpenAI-compatible endpoint (OpenAI, OpenRouter, …), and OpenAI
models via "Sign in with ChatGPT" (Codex OAuth — `zuse --login`).

```bash
zuse                          # local (Ollama)
zuse --provider anthropic     # Claude (needs ANTHROPIC_API_KEY)
OPENAI_API_KEY=… zuse --provider openai -m gpt-4o   # OpenAI / OpenRouter (--openai-base-url)
zuse --login                  # OAuth sign-in with ChatGPT, then:
zuse --provider codex -m gpt-5   # use OpenAI's model via your ChatGPT plan (experimental)
```

```
 ______
|___  /
   / / _   _ ___  ___
  / / | | | / __|/ _ \
 / /__| |_| \__ \  __/
/_____|\__,_|___/\___|
```

## Features

- **Agentic tool loop** with live, streaming Markdown output and visible reasoning.
- **Continuous learning** — before each task Zuse recalls relevant things it has
  learned; after each task it reflects and saves durable knowledge (preferences,
  facts, procedures) to `~/.zuse/knowledge.jsonl`. It genuinely gets better the
  more you use it, across sessions.
- **Vision + computer use** — `screen` shows Zuse the actual screen (image to a
  vision-capable model), and it controls the Mac at pixel coordinates with
  `mouse_click`, `mouse_move`, `type_text`, and `key_press` (via Quartz). Best with
  a vision model or Claude; needs Accessibility + Screen Recording permission.
- **Full macOS control** — also `applescript` (automate any app + System Events
  keystrokes/clicks), `open`, `clipboard_read`/`clipboard_write`, `screenshot`,
  `notify`, and `system_info`.
- **MCP client** — connect to any [Model Context Protocol](https://modelcontextprotocol.io)
  server (GitHub, filesystem, fetch, Slack, …) via `~/.zuse/mcp.json`. Their tools
  are auto-discovered and exposed as `mcp__<server>__<tool>`; `/mcp` lists them.
- **Browser automation** — drive a real Chromium (JS-rendered sites) with
  `browser_open`, `browser_read`, `browser_links`, `browser_click`,
  `browser_type`, and `browser_screenshot`. Headless by default; `--browser-window`
  shows it. (Optional: `pip install -e ".[browser]" && python -m playwright install chromium`.)
- **Safety: diff previews, undo, project rules** — file edits show a colored diff
  before they're applied; `/undo` reverts the last change; a project's `AGENTS.md`
  / `.zuse.md` is auto-loaded into the prompt so Zuse follows that repo's conventions.
- **Persistent shell + background tasks** — `bash` runs in a stateful session
  (`cd`, env, and venv activation persist between calls); `run_background` /
  `bg_logs` / `bg_stop` / `bg_list` manage long-running processes like dev servers.
- **Autonomous goal mode** — `/goal <text>` makes Zuse plan, act, verify (run
  tests), and keep going across rounds until the goal is achieved or it's blocked.
- **Context compaction** — long conversations are auto-summarized when they
  approach the context window (essential for local models), so sessions don't run
  out of room.
- **Rich tool set**: `read_file`, `write_file`, `edit_file`, `list_directory`,
  `glob`, `grep`, `python`, `todo_write`, `remember`, `task` (sub-agent),
  plus server-side `web_search` and `web_fetch` (cloud).
- **Permission system** — side-effecting actions (writes, edits, shell, code,
  AppleScript, clicks, typing) ask for confirmation, with per-tool "always allow"
  and a global `--yolo` mode.
- **Planning** — the agent maintains a visible task list for multi-step work.
- **Sessions** — save and reload conversations.
- **Cost tracking** — live token usage and USD cost estimates (free for local
  models), with prompt caching of the system + tool prefix.
- **Sub-agents** — delegate isolated sub-tasks to nested agent loops.
- **Configurable** — provider, model, effort, thinking, learning, web, persona.

## Install

```bash
cd /Users/nik/agent
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### Run locally (no API key)

Install [Ollama](https://ollama.com), start it, and pull a tool-capable model:

```bash
ollama serve            # if not already running
ollama pull qwen2.5     # or llama3.1, qwen2.5-coder, mistral-nemo, qwen3
zuse                  # auto-detects local model; no key needed
zuse --list-models    # show installed local models
```

With no `ANTHROPIC_API_KEY` set, Zuse automatically uses the local backend.
Tip: small reasoning models can overthink — add `--no-thinking` for snappy local runs.

### Run with Claude (cloud)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
zuse                          # uses Claude automatically when a key is present
zuse --provider anthropic ... # force the cloud backend
```

## Usage

Interactive REPL:

```bash
zuse                  # local if no key, else Claude
zuse --local          # force local Ollama
```

One-shot (non-interactive):

```bash
zuse --local --no-thinking "summarize what this project does and list its files"
zuse -m sonnet -e medium "refactor utils.py for readability"
zuse --local -m qwen2.5-coder --yolo "run the test suite and fix any failures"
```

### Slash commands

| Command | Description |
|---|---|
| `/help` | List commands |
| `/clear` | Clear the conversation |
| `/model <name>` | Switch model (`opus`, `sonnet`, `haiku`, `fable`) |
| `/effort <level>` | `low \| medium \| high \| xhigh \| max` |
| `/thinking` | Toggle visible reasoning |
| `/learning` | Toggle continuous learning |
| `/yolo` | Toggle auto-approve for tool permissions |
| `/tools` | List available tools |
| `/cost` | Token usage and estimated cost |
| `/memory`, `/forget` | Show / clear learned knowledge |
| `/save <name>`, `/load <name>`, `/sessions` | Conversation persistence |
| `/system` | Show the active system prompt |
| `/exit` | Quit |

## Continuous learning

Zuse keeps a growing knowledge base at `~/.zuse/knowledge.jsonl`:

- **Recall** — before each task, the most relevant entries are pulled in (keyword
  match by default; semantic search if you set an embedding model via
  `--embed-model nomic-embed-text`). Preferences are always present in the prompt.
- **Reflect** — after each substantive task, a short low-effort pass extracts 0–3
  durable lessons and stores them, deduplicated.
- **Remember** — the agent (or you, via a request) can save things explicitly.

Inspect it with `/memory`, wipe it with `/forget`, or disable the reflection pass
with `--no-learning`.

> Note: the recall/learn pipeline is model-agnostic, but a model needs to be
> capable enough to *act* on recalled preferences. Tiny local models (≤1B) store
> and recall fine but may ignore the guidance — use `qwen2.5`+ or Claude for that.

## macOS control

On macOS, Zuse can operate the machine directly: `applescript` (the most powerful
— automate any app, send keystrokes/clicks via System Events), `open` (files,
URLs, apps), `clipboard_read`/`clipboard_write`, `screenshot`, `notify`, and
`system_info`. These side-effecting tools are permission-gated.

## MCP servers

Drop a `~/.zuse/mcp.json` to connect MCP servers (started over stdio). Their
tools load automatically on the next run and appear as `mcp__<server>__<tool>`;
inspect them with `/mcp`.

```json
{
  "mcpServers": {
    "filesystem": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/nik"]},
    "fetch":      {"command": "uvx", "args": ["mcp-server-fetch"]}
  }
}
```

No config file → no MCP overhead. Add `"disabled": true` to a server to skip it.

## Configuration

Settings persist in `~/.zuse/config.json` (provider, model, effort, thinking,
learning, web access, persona). Environment overrides: `ANTHROPIC_API_KEY`,
`ZUSE_MODEL`, `ZUSE_HOME`, `OLLAMA_HOST`.

## Architecture

```
zuse/
  cli.py          REPL, slash commands, provider selection, one-shot mode
  agent.py        Provider-neutral agentic loop, learning loop, sub-agent runner
  config.py       Config, pricing, system-prompt builder
  knowledge.py    Growing knowledge store: recall + dedupe + reflection storage
  embeddings.py   Optional local embeddings (Ollama) for semantic recall
  ui.py           Banner, live Markdown stream, tool panels, todos
  permissions.py  Confirmation gating
  costs.py        Token/cost accounting (free for local models)
  session.py      Save/load conversations
  providers/      Pluggable model backends behind one interface:
    base.py         ToolCall / ToolResult / StepResult + Backend ABC
    anthropic_backend.py   Claude: streaming, caching, adaptive thinking, effort, web tools
    ollama_backend.py      Local: /api/chat streaming, tool calls, <think> extraction
  tools/          read/write/edit/ls/glob/grep, bash, python, todo, remember,
                  task (sub-agent), and on macOS: applescript, open, clipboard,
                  screenshot, notify, system_info (mac.py)
```

The agent talks to any backend through a single `Backend` interface, so the same
tool loop, permissions, and UI work identically whether the model is a local
Ollama model (offline, free) or Claude via the Anthropic API (default
`claude-opus-4-8`, with adaptive thinking, effort, and prompt caching).

## Safety

Zuse executes shell commands and edits files on your machine. It asks before
each side-effecting action unless you enable `--yolo`. Obvious destructive commands
(`rm -rf /`, fork bombs, `mkfs`, raw `dd`) are hard-blocked. Use it on code you can
restore from version control.
