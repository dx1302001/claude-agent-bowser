# Agent-Browser Enhanced

Enhanced browser automation skill for [Claude Code](https://claude.ai/code), wrapping [vercel-labs/agent-browser](https://github.com/vercel-labs/agent-browser) with **3 superpowers**.

## Features

### 🅰️ Long Prompt Handling (No Line-Break Loss)
Send multi-line JavaScript to the browser without shell escaping issues.

```bash
# Write any JS — backticks, $, braces, regex — no escaping needed
cat > script.js << 'EOF'
const items = [...document.querySelectorAll('.product')];
items.forEach((el, i) => console.log(`${i}: ${el.textContent.trim()}`));
EOF
python agent_browser_helper.py eval-js script.js
```

### 🅱️ Task Completion Detection
Verify browser tasks completed with structured success/failure verdicts.

```bash
python agent_browser_helper.py check-completion \
  --expect-url "**/dashboard" \
  --expect-text "Welcome" \
  --reject-text "error" \
  --json
```

### 🅲 Complete Content Retrieval
Get full page content in 5 modes — beyond the accessibility tree snapshot.

```bash
# Structured data extraction
python agent_browser_helper.py get-content --mode json --output page.json

# One-shot: navigate + scroll + extract
python agent_browser_helper.py extract-all "https://example.com" --mode text
```

## Installation

### Prerequisites
- **Node.js 18+** and npm
- **Python 3.7+** (stdlib only, no pip installs)
- **Google Chrome** or Chromium

### Install agent-browser
```bash
npm install -g agent-browser
agent-browser install          # Downloads Chromium
```

### Install This Skill

**Option 1: Clone as standalone tool**
```bash
git clone https://github.com/dx1302001/claude-agent-bowser.git
cd agent-browser-enhanced
python agent_browser_helper.py --help
```

**Option 2: Install as Claude Code skill**
```bash
# Copy the skill definition
cp SKILL.md ~/.claude/skills/agent-browser-enhanced.md

# Or add to Claude Code settings
# In ~/.claude/settings.local.json, add to the skills array:
# { "name": "agent-browser-enhanced", ... }
```

## Usage

### As a Claude Code Skill
The skill auto-activates when you mention browser automation, web scraping, form filling, page testing, or content extraction. Use `/agent-browser-enhanced` to invoke directly.

### As a Standalone CLI

```bash
# Execute JavaScript in the browser
python agent_browser_helper.py eval-js script.js
python agent_browser_helper.py eval-js --base64 "ZG9jdW1lbnQudGl0bGU="
echo 'document.title' | python agent_browser_helper.py eval-js --stdin

# Check if a task completed
python agent_browser_helper.py check-completion \
  --expect-url "**/success" \
  --expect-text "Confirmed" \
  --json

# Extract page content
python agent_browser_helper.py get-content --mode text
python agent_browser_helper.py get-content --mode json --output data.json
python agent_browser_helper.py get-content --mode full --scroll

# One-shot: navigate + extract
python agent_browser_helper.py extract-all "https://example.com" --mode structured
```

## Command Reference

| Command | Capability | Description |
|---------|-----------|-------------|
| `eval-js <file>` | A | Execute JS from file/base64/stdin (no shell escaping) |
| `check-completion` | B | Verify task success with URL/text/element/JS checks |
| `get-content` | C | Extract page content in 5 modes |
| `extract-all <url>` | Convenience | Navigate + wait + scroll + extract in one step |

### get-content Modes

| Mode | Output | Best For |
|------|--------|----------|
| `text` | Plain visible text | Reading articles, NLP |
| `html` | Full `body.innerHTML` | Raw HTML processing |
| `json` | Structured JSON (headings, links, tables, lists, meta) | Data extraction |
| `full` | Text + snapshot + JSON combined | Comprehensive capture |
| `structured` | Alias for `json` | Same as json |

## How It Works

```
┌─────────────┐     ┌─────────────────────┐     ┌──────────────────┐
│  SKILL.md   │ ──▶ │ agent_browser_helper  │ ──▶ │  agent-browser   │
│  (Claude)   │     │ (Python, subprocess)  │     │  (Rust CLI, CDP) │
└─────────────┘     └─────────────────────┘     └──────────────────┘
```

The Python helper uses `subprocess.run(..., shell=False)` to call agent-browser CLI. This completely bypasses the shell, eliminating all escaping issues (Cap A). It builds structured completion checks (Cap B) and layered content extraction (Cap C) on top of agent-browser's primitive commands.

## License

MIT
