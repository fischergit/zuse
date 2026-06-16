# Zuse

<p align="center">
  <img src="assets/zuse-logo.png" alt="Zuse logo" width="420">
</p>

<p align="center">
  <strong>Autonomous terminal AI agent for macOS, code, shell, browser automation and local workflows.</strong>
</p>

Zuse is an agentic CLI inspired by tools like OpenClaw and Hermes. It can read and edit files, run shell commands, use Python, control your Mac, browse the web, manage todos, spawn sub-agents and remember useful facts across sessions.

By default, Zuse runs locally through [Ollama](https://ollama.com) when no API key is configured. It can also use Claude, OpenAI-compatible endpoints, and OpenAI/Codex via ChatGPT OAuth.

---

## Quick start

```bash
cd /Users/nik/agent
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Local mode with Ollama

```bash
ollama serve
ollama pull qwen2.5
zuse
```

### Claude / cloud mode

```bash
export ANTHROPIC_API_KEY=sk-ant-...
zuse --provider anthropic
```

### ChatGPT / Codex OAuth

```bash
zuse --login
zuse --provider codex -m gpt-5
```

---

## Main commands

| Command | What it starts |
|---|---|
| `zuse` | Terminal REPL |
| `zuse "fix the failing tests"` | One-shot task |
| `zuse-web` | Local browser WebGUI at `127.0.0.1:8765` |
| `zuse-gui` | Native Tkinter desktop GUI |
| `zuse-whatsapp` | WhatsApp bridge |
| `zuse-telegram` | Telegram bot |

The WebGUI is intentionally separate: `zuse` starts the terminal REPL, `zuse-web` starts the browser UI.

---

## Common examples

```bash
# Terminal REPL
zuse
zuse --local
zuse --provider codex

# WebGUI
zuse-web
zuse-web --provider codex
zuse-web --local
zuse-web --no-open

# Native GUI
zuse-gui
zuse-gui --provider codex --auto
zuse-gui --local --auto

# Diagnostics / one-shot tasks
zuse --doctor
zuse --selftest
zuse --local --no-thinking "summarize this project"
zuse --local -m qwen2.5-coder --yolo "run the test suite and fix failures"
```

---

## Highlights

- **Agentic tool loop** — plans, acts, verifies and continues until the task is done.
- **File editing with safety** — colored diffs before edits, undo support, project rules via `AGENTS.md` / `.zuse.md`.
- **Persistent shell** — `cd`, environment changes and venv activation persist during a session.
- **macOS control** — AppleScript, app opening, screenshots, clipboard, notifications and system info.
- **Computer use** — screen inspection plus mouse and keyboard actions on macOS.
- **Browser automation** — real Chromium automation for JS-rendered sites.
- **MCP support** — connect external Model Context Protocol servers through `~/.zuse/mcp.json`.
- **Continuous learning** — stores durable preferences, facts and procedures in `~/.zuse/knowledge.jsonl`.
- **Sub-agents** — delegate isolated research or implementation subtasks.
- **Cost and rate-limit visibility** — `/cost` plus Codex rate-limit display where headers are available.
- **Multiple interfaces** — terminal, WebGUI, native GUI, WhatsApp and Telegram.

---

## Providers

| Provider | Command | Notes |
|---|---|---|
| Ollama | `zuse --local` | Local/offline, free, default when no cloud key is set |
| Anthropic Claude | `zuse --provider anthropic` | Requires `ANTHROPIC_API_KEY` |
| OpenAI-compatible | `OPENAI_API_KEY=... zuse --provider openai -m gpt-4o` | Supports custom `--openai-base-url` |
| Codex OAuth | `zuse --login` then `zuse --provider codex` | Uses ChatGPT OAuth credentials |

Useful model flags:

```bash
zuse -m sonnet
zuse --local -m qwen2.5-coder
zuse --provider codex -m gpt-5
zuse -e medium          # reasoning effort: low, medium, high, xhigh, max
zuse --no-thinking      # faster local responses on small models
```

---

## Slash commands

| Command | Description |
|---|---|
| `/help` | Show commands |
| `/doctor` | Check local setup |
| `/selftest` | Exercise core tools safely |
| `/clear` | Clear current conversation |
| `/undo` | Revert the last file change |
| `/goal <text>` | Autonomous goal mode |
| `/model <name>` | Switch model |
| `/effort <level>` | Set reasoning effort |
| `/thinking` | Toggle visible reasoning |
| `/learning` | Toggle continuous learning |
| `/auto` | Toggle autonomous approvals |
| `/yolo` | Auto-approve tool permissions |
| `/tools` | List available tools |
| `/mcp` | Show connected MCP servers |
| `/cost` | Show token/cost summary |
| `/ratelimit` | Show Codex rate-limit usage when available |
| `/memory` / `/forget` | Show or clear learned knowledge |
| `/save <name>` / `/load <name>` / `/sessions` | Session persistence |
| `/system` | Show the active system prompt |
| `/exit` | Quit |

---

## Optional capabilities

### Browser automation

```bash
pip install -e ".[browser]"
python -m playwright install chromium
zuse --browser-window
```

Tools include `browser_open`, `browser_read`, `browser_links`, `browser_click`, `browser_type` and `browser_screenshot`.

### macOS permissions

For screen, mouse and keyboard control, macOS may ask for:

- Accessibility
- Screen Recording
- Automation permissions for controlled apps

Side-effecting actions are permission-gated unless `--yolo` is enabled.

### MCP servers

Create `~/.zuse/mcp.json`:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/nik"]
    },
    "fetch": {
      "command": "uvx",
      "args": ["mcp-server-fetch"]
    }
  }
}
```

Use `/mcp` to inspect loaded servers and tools. Add `"disabled": true` to skip a server.

---

## Continuous learning

Zuse stores durable knowledge in:

```text
~/.zuse/knowledge.jsonl
```

It can remember preferences, project facts and reusable procedures. Relevant memories are recalled before each task. Disable reflection with:

```bash
zuse --no-learning
```

Inspect or clear memory in the REPL:

```text
/memory
/forget
```

---

## WhatsApp bridge

Zuse supports two WhatsApp modes.

### QR mode

The easiest setup: scan a WhatsApp Web QR code and chat with Zuse.

```bash
cd /Users/nik/agent
source .venv/bin/activate
pip install -e ".[whatsapp]"

zuse-whatsapp --mode qr --provider codex --auto
# or local:
zuse-whatsapp --mode qr --local --auto
```

The QR session is stored under:

```text
~/.zuse/whatsapp-web-bridge
```

QR mode keeps one persistent Zuse agent in the Python process. WhatsApp messages and local terminal input share the same conversation, tools, shell session, background tasks, memory and Mac access.

Optional allow-list:

```bash
zuse-whatsapp --mode qr --allowed-sender 491701234567 --provider codex --auto
```

### Meta Cloud API webhook

```bash
export ZUSE_WHATSAPP_VERIFY_TOKEN="choose-a-long-random-token"
export WHATSAPP_ACCESS_TOKEN="EAAG..."
export WHATSAPP_PHONE_NUMBER_ID="1234567890"
export WHATSAPP_APP_SECRET="..."
export ZUSE_WHATSAPP_ALLOWED_SENDERS="491701234567"

zuse-whatsapp --mode cloud --provider codex --auto
```

Webhook endpoint:

```text
http://127.0.0.1:8787/webhook/whatsapp
```

For local Meta testing, expose it with:

```bash
ngrok http 8787
```

---

## Telegram bot

```bash
cd /Users/nik/agent
source .venv/bin/activate
pip install -e .

# Create a bot with @BotFather, then:
export TELEGRAM_BOT_TOKEN="123456:ABC..."
zuse-telegram --provider codex --auto
```

Restrict the bot to your chat:

```bash
zuse-telegram --allowed-chat-id 123456789 --provider codex --auto
# or:
export ZUSE_TELEGRAM_ALLOWED_CHAT_IDS="123456789"
zuse-telegram --provider codex --auto
```

Telegram mode also shares one persistent local Zuse session with the terminal input.

---

## Configuration

Settings persist in:

```text
~/.zuse/config.json
```

Common environment variables:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key |
| `OPENAI_API_KEY` | OpenAI/OpenAI-compatible API key |
| `OLLAMA_HOST` | Ollama host override |
| `ZUSE_MODEL` | Default model override |
| `ZUSE_HOME` | Zuse config/data directory |

---

## Safety

Zuse can execute commands and edit files on your machine. By default it asks before side-effecting actions. Use `--yolo` only in trusted projects and sessions.

Hard-blocked destructive patterns include obvious cases like `rm -rf /`, fork bombs, `mkfs` and raw destructive `dd` usage. Still: use version control and review important changes.
