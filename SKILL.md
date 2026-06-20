---
name: agent-browser-enhanced
description: >-
  Enhanced browser automation skill wrapping vercel-labs/agent-browser with 3
  superpowers: (A) long prompt handling without line-break loss via subprocess
  bypass, (B) task completion detection with structured success/failure
  verdicts, (C) complete page content retrieval in 5 extraction modes. Use
  when the user wants to browse the web, fill forms, extract data, scrape
  content, automate web tasks, or test web applications. Triggers on: browser
  automation, web scraping, form filling, page testing, navigate website,
  extract content, check page, verify site.
allowed-tools:
  - Bash(agent-browser:*)
  - "Bash(python agent_browser_helper.py*:*)"
  - Write
  - Read
---

# Agent-Browser Enhanced

Wraps [vercel-labs/agent-browser](https://github.com/vercel-labs/agent-browser) (v0.28+) with three enhanced capabilities via a Python helper script.

```
┌──────────────────┐     ┌─────────────────────────┐     ┌──────────────────┐
│  Claude Code     │ ──▶ │  agent_browser_helper.py │ ──▶ │  agent-browser   │
│  (SKILL.md)      │     │  (3 superpowers)         │     │  (Chromium/CDP)  │
└──────────────────┘     └─────────────────────────┘     └──────────────────┘
```

## Prerequisites

```bash
npm install -g agent-browser
agent-browser install
```

The helper script requires **Python 3.7+** with no external dependencies (stdlib only).

Save the helper script from this skill's repo to your working directory or add it to PATH.

## Quick Reference

```
agent-browser <cmd>              → Raw CLI for simple operations
python agent_browser_helper.py   → Enhanced commands for the 3 superpowers
```

---

## Superpower A: Long Prompt Handling (No Line-Break Loss)

**Problem**: Sending multi-line JavaScript through Bash causes line breaks, backticks, `$` signs, and braces to get mangled by shell escaping.

**Solution**: The `eval-js` command reads JS from a file, stdin pipe, or base64 string, then passes it via `subprocess.Popen(..., shell=False)` — completely bypassing the shell.

### Usage

```bash
# Method 1: Write JS to a file first (BEST for multi-line scripts)
cat > /tmp/extract.js << 'EOF'
const items = document.querySelectorAll('.product-card');
const results = [];
items.forEach((el, i) => {
  const name = el.querySelector('.title')?.textContent?.trim();
  const price = el.querySelector('.price')?.textContent?.trim();
  results.push({ index: i, name, price });
});
JSON.stringify(results, null, 2);
EOF
python agent_browser_helper.py eval-js /tmp/extract.js

# Method 2: Base64-encoded (GOOD for medium scripts, completely shell-safe)
python agent_browser_helper.py eval-js --base64 "ZG9jdW1lbnQudGl0bGU="

# Method 3: Stdin pipe
echo "document.title" | python agent_browser_helper.py eval-js --stdin

# Method 4: Direct agent-browser for one-liners (FAST but avoid special chars)
agent-browser eval "document.title"
```

### When to Use Which

| Scenario | Use |
|----------|-----|
| One-liner, no special chars | `agent-browser eval "<js>"` |
| Multi-line, backticks, braces | `eval-js <file>` |
| Template literals / `$` signs | `eval-js --base64` |
| Part of a piped workflow | `eval-js --stdin` |

---

## Superpower B: Task Completion Detection

**Problem**: agent-browser has no built-in "task done" signal. You must manually inspect the page after each action.

**Solution**: The `check-completion` command runs a battery of checks against the current page and returns a structured verdict with confidence level.

### Check Methods (in priority order)

| Method | Flag | What It Checks |
|--------|------|---------------|
| URL match | `--expect-url "**/dashboard"` | Navigated to expected URL (glob pattern) |
| Text presence | `--expect-text "Welcome back"` | Success text exists on page |
| Element visible | `--expect-element ".success-msg"` | Success element is visible (CSS or @ref) |
| JS expression | `--expect-js "document.querySelectorAll('.row').length > 10"` | Custom condition is truthy |
| Failure text | `--reject-text "Invalid password"` | Error text must NOT exist |
| Failure element | `--reject-element ".error-banner"` | Error element must NOT be visible |

### Usage Examples

```bash
# After login — verify we reached the dashboard
python agent_browser_helper.py check-completion \
  --expect-url "**/dashboard" \
  --expect-text "Welcome" \
  --reject-text "Invalid" \
  --json

# After form submission — check for success message
python agent_browser_helper.py check-completion \
  --expect-text "Thank you for your submission" \
  --expect-element ".alert-success" \
  --reject-element ".alert-danger"

# After data loading — verify items appeared
python agent_browser_helper.py check-completion \
  --expect-js "document.querySelectorAll('.data-row').length >= 20" \
  --wait-ms 10000

# Check SPAs — wait for specific route without full page load
python agent_browser_helper.py check-completion \
  --expect-js "window.location.hash === '#/settings'" \
  --expect-text "Account Settings"
```

### Return Format (with `--json`)

```json
{
  "completed": true,
  "confidence": "high",
  "details": {
    "url": "https://app.example.com/dashboard",
    "checks_passed": 3,
    "checks_total": 3,
    "rejected": false,
    "checks": [
      {"name": "url_match", "passed": true, "detail": "URL='...' pattern='**/dashboard' match=YES"},
      {"name": "text_match", "passed": true, "detail": "'Welcome' FOUND (page=12450 chars)"},
      {"name": "reject_text(Invalid)", "passed": true, "detail": "'Invalid' not found (good)"}
    ]
  }
}
```

### Completion Protocol (Recommended Workflow)

1. **BEFORE** acting: take a snapshot (`agent-browser snapshot -i`) to confirm starting state
2. **ACT**: perform interactions (click, fill, submit)
3. **WAIT**: `agent-browser wait --load networkidle`
4. **CHECK**: call `check-completion` with your success criteria
5. **IF failed**: snapshot current state, diagnose, retry or re-plan

---

## Superpower C: Complete Content Retrieval

**Problem**: `agent-browser snapshot` returns only the accessibility tree (~200-400 tokens of interactive elements). You often need the full page text, structured data, or embedded metadata.

**Solution**: The `get-content` command extracts page content in 5 modes, with automatic file-saving for large content to prevent shell truncation.

### Extraction Modes

| Mode | Description | Best For | Typical Size |
|------|-------------|----------|-------------|
| `text` | Plain visible text (TreeWalker) | Reading articles, analysis | 5-50 KB |
| `html` | Full `body.innerHTML` | Raw HTML processing | 50 KB - 5 MB |
| `json` | Structured data (headings, links, tables, lists, paragraphs, meta) | Data extraction, APIs | 10-100 KB |
| `full` | Text + accessibility snapshot + JSON — everything | Comprehensive capture | 50-500 KB |
| `structured` | Alias for `json` | Same as json | 10-100 KB |

### Usage Examples

```bash
# Read an article as plain text
python agent_browser_helper.py get-content --mode text --output article.txt

# Extract structured data from a product listing page
python agent_browser_helper.py get-content --mode json --output products.json

# Full capture for offline analysis
python agent_browser_helper.py get-content --mode full --output /tmp/page_dump.txt

# Infinite-scroll page: scroll to load all content first
python agent_browser_helper.py get-content --mode json --scroll --scroll-max 20

# One-shot: navigate + wait + extract
python agent_browser_helper.py extract-all "https://example.com/blog" --mode text
```

### Output Handling

- Content **under 50 KB**: returned directly via stdout
- Content **over 50 KB**: automatically saved to a temp file (path printed)
- Use `--output <path>` to always save to a specific file

---

## Common Workflows

### Workflow 1: Research / Read an Article

```bash
agent-browser open "https://example.com/article"
agent-browser wait --load networkidle
python agent_browser_helper.py get-content --mode text --output /tmp/article.txt
cat /tmp/article.txt
```

### Workflow 2: Form Filling with Verification

```bash
agent-browser open "https://example.com/signup"
agent-browser snapshot -i
# Use the @eN refs from snapshot to fill the form
agent-browser fill @e3 "user@example.com"
agent-browser fill @e4 "SecurePass123!"
agent-browser click @e6
# Wait and verify
agent-browser wait --load networkidle
python agent_browser_helper.py check-completion \
  --expect-url "**/welcome" \
  --expect-text "Account created" \
  --reject-text "error" \
  --json
```

### Workflow 3: Data Scraping with Infinite Scroll

```bash
agent-browser open "https://example.com/products"
agent-browser wait --load networkidle
# Scroll to load all products, then extract structured data
python agent_browser_helper.py get-content \
  --mode json \
  --scroll --scroll-max 20 \
  --output /tmp/products.json
# Quick summary from extracted data
python -c "
import json
data = json.load(open('/tmp/products.json'))
print(f'{len(data.get(\"links\",[]))} products, {len(data.get(\"headings\",[]))} headings')
"
```

### Workflow 4: Multi-Page Form Test

```bash
# Page 1: Fill and submit
agent-browser open "https://example.com/checkout/step-1"
agent-browser fill @e2 "test@example.com"
agent-browser click @e5
agent-browser wait --load networkidle

# Verify we advanced to step 2
python agent_browser_helper.py check-completion \
  --expect-url "**/step-2" \
  --expect-text "Shipping" \
  --json
```

---

## Error Recovery

### "No active browser session"
```bash
agent-browser close --all
agent-browser open "https://example.com"
```

### check-completion timed out
1. `agent-browser snapshot -i` — see current state
2. `agent-browser get url` — check if navigation happened
3. Adjust your criteria (maybe the page changed)

### get-content returns empty
1. Wait for network idle: `agent-browser wait --load networkidle`
2. Try `--mode text` instead of `--mode json` (some pages render client-side)
3. Check if the page actually loaded: `agent-browser get title`

### Stale element ref (@e1 no longer valid)
```bash
agent-browser snapshot -i   # Re-snapshot to get fresh refs
# Find your element by text or role instead:
agent-browser find text "Submit" click
```

---

## Agent-Browser CLI Cheatsheet

| Category | Command | Purpose |
|----------|---------|---------|
| **Navigate** | `open <url>`, `goto <url>` | Go to URL |
| | `back`, `forward`, `reload` | History navigation |
| **See** | `snapshot -i` | Interactive elements with @refs |
| | `snapshot -i --json` | Machine-readable snapshot |
| | `snapshot -c` | Compact snapshot |
| **Act** | `click @e1` | Click element |
| | `fill @e1 "text"` | Clear + type into input |
| | `type @e1 "text"` | Type without clearing |
| | `press @e1 Enter` | Send key event |
| | `select @e1 "option"` | Select dropdown option |
| | `hover @e1` | Hover over element |
| | `scroll @e1` | Scroll element into view |
| **Read** | `get text @e1` | Visible text of element |
| | `get text body` | Full page visible text |
| | `get html @e1` | Inner HTML of element |
| | `get value @e1` | Input value |
| | `get attr @e1 href` | Element attribute |
| | `get title` | Page title |
| | `get url` | Current URL |
| **Check** | `is visible @e1` | Element visibility |
| | `is enabled @e1` | Element enabled state |
| | `is checked @e1` | Checkbox/radio state |
| **Wait** | `wait --load networkidle` | Page fully loaded |
| | `wait --text "text"` | Text appears on page |
| | `wait --url "**/path"` | URL matches glob |
| | `wait <ms>` | Fixed duration |
| | `wait --fn "condition"` | JS condition met |
| **Capture** | `screenshot [path]` | Viewport screenshot |
| | `screenshot --full` | Full-page screenshot |
| | `screenshot --annotate` | Annotated with @refs |
| | `pdf output.pdf` | Page as PDF |
| **Eval** | `eval "document.title"` | Execute JS |
| | `eval --stdin` | JS from stdin |
| | `eval -b "<base64>"` | Base64 JS |
| **Network** | `network requests` | List network requests |
| | `network har start/stop` | Record HAR |
| **Find** | `find text "..." click` | Find by text and click |
| | `find role button click` | Find by role and click |
| **Manage** | `close` | Close current tab |
| | `close --all` | Close all sessions |
| | `set viewport 1920 1080` | Set viewport size |
| | `set device "iPhone 14"` | Mobile device emulation |
