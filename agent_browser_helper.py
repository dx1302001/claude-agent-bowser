#!/usr/bin/env python3
"""
agent_browser_helper.py - Enhanced wrapper for agent-browser CLI.

Three superpowers:
  Cap A: Long prompt handling — multi-line JS without line-break loss
  Cap B: Task completion detection — structured success/failure verdicts
  Cap C: Complete content retrieval — full page extraction beyond snapshot

Usage:
  python agent_browser_helper.py eval-js <file> [--base64 <data> | --stdin]
  python agent_browser_helper.py check-completion [options]
  python agent_browser_helper.py get-content [options]
  python agent_browser_helper.py extract-all <url> [options]

Dependencies: Python 3.7+ (stdlib only — no pip install required)
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import fnmatch

# =============================================================================
# Constants
# =============================================================================

AGENT_BROWSER_CMD = "agent-browser"
DEFAULT_WAIT_MS = 5000
CONTENT_WARN_THRESHOLD = 50 * 1024  # 50 KB — auto-save to file above this


# =============================================================================
# Core: Safe subprocess runner (shell=False avoids ALL escaping issues)
# =============================================================================

def _run_ab(cmd_args, stdin_data=None, timeout=30):
    """
    Run an agent-browser command via subprocess with shell=False.
    This is the foundation of Capability A — by bypassing the shell entirely,
    multi-line JS with special characters (backticks, $, braces, regex) is
    passed verbatim without corruption.
    """
    full_cmd = [AGENT_BROWSER_CMD] + cmd_args
    try:
        result = subprocess.run(
            full_cmd,
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except FileNotFoundError:
        return {
            "stdout": "",
            "stderr": (
                f"Error: '{AGENT_BROWSER_CMD}' not found. "
                "Install it: npm i -g agent-browser && agent-browser install"
            ),
            "returncode": -1,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"Error: Command timed out after {timeout}s",
            "returncode": -1,
        }
    except Exception as e:
        return {"stdout": "", "stderr": f"Error: {e}", "returncode": -1}


def _run_ab_js(js_code, timeout=30):
    """Execute JavaScript in the browser via agent-browser eval --stdin."""
    return _run_ab(["eval", "--stdin", "--json"], stdin_data=js_code, timeout=timeout)


# =============================================================================
# Capability A: Long Prompt Handling (no line-break loss)
# =============================================================================

def cmd_eval_js(args):
    """
    Execute JavaScript in the browser without shell escaping issues.

    Three input methods (priority order):
      1. --base64 <data>   — base64-encoded JS (completely shell-safe)
      2. <file>            — read JS from a file (best for multi-line scripts)
      3. --stdin           — read JS from stdin pipe
    """
    js_code = None

    if args.base64:
        try:
            js_code = base64.b64decode(args.base64).decode("utf-8")
        except Exception as e:
            return _error(f"Base64 decode failed: {e}")

    elif args.file:
        file_path = args.file
        # Try relative paths relative to CWD
        if not os.path.isfile(file_path):
            alt = os.path.join(os.getcwd(), file_path)
            if os.path.isfile(alt):
                file_path = alt
            else:
                return _error(f"File not found: {args.file}")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                js_code = f.read()
        except Exception as e:
            return _error(f"File read failed: {e}")

    else:
        # Stdin mode
        if not sys.stdin.isatty():
            js_code = sys.stdin.read()
        else:
            return _error(
                "No JavaScript provided. Use one of:\n"
                "  python agent_browser_helper.py eval-js <file>\n"
                "  python agent_browser_helper.py eval-js --base64 <data>\n"
                "  echo '...' | python agent_browser_helper.py eval-js --stdin"
            )

    if not js_code or not js_code.strip():
        return _error("No JavaScript code provided (empty input)")

    result = _run_ab_js(js_code, timeout=args.timeout)

    output = {
        "input_size": len(js_code),
        "input_lines": js_code.count("\n") + 1,
    }

    if args.json:
        try:
            output["result"] = json.loads(result["stdout"])
        except (json.JSONDecodeError, TypeError):
            output["result"] = result["stdout"]
    else:
        output["result"] = result["stdout"]

    output["stderr"] = result["stderr"]
    output["returncode"] = result["returncode"]
    output["success"] = result["returncode"] == 0 and not result["stderr"].startswith("Error")

    return output


# =============================================================================
# Capability B: Task Completion Detection
# =============================================================================

def _glob_to_regex(pattern):
    """Convert a glob pattern (with ** and *) to a regex."""
    # Escape regex special chars except * and ?
    escaped = re.escape(pattern)
    # Unescape ** (glob star-star) → .*
    escaped = escaped.replace(r"\*\*", ".*")
    # Unescape * (glob star) → [^/]*
    escaped = escaped.replace(r"\*", "[^/]*")
    return "^" + escaped + "$"


def _check_url(pattern):
    """Check if the current page URL matches a glob pattern."""
    r = _run_ab(["get", "url"])
    if r["returncode"] != 0:
        return {"name": "url_match", "passed": False, "detail": f"Failed to get URL: {r['stderr']}"}

    current_url = r["stdout"].strip()
    matched = fnmatch.fnmatch(current_url, pattern)

    return {
        "name": "url_match",
        "passed": matched,
        "detail": f"URL='{current_url}' pattern='{pattern}' match={'YES' if matched else 'NO'}",
    }


def _check_text(text, expect_present=True):
    """Check if text is present (or absent) on the page."""
    safe_text = json.dumps(text)
    # Inject JS to search page body text
    js = (
        f"(function(){{"
        f"var t=document.body?document.body.innerText:'';"
        f"var found=t.indexOf({safe_text})!==-1;"
        f"return JSON.stringify({{found:found,pageLen:t.length}});"
        f"}})();"
    )
    r = _run_ab_js(js)
    if r["returncode"] != 0:
        return {"name": "text_check", "passed": False, "detail": f"JS eval failed: {r['stderr']}"}

    try:
        data = json.loads(r["stdout"])
        found = data.get("found", False)
        display = text[:80] + ("..." if len(text) > 80 else "")
        if expect_present:
            return {
                "name": "text_match",
                "passed": found,
                "detail": f"'{display}' {'FOUND' if found else 'NOT FOUND'} (page={data.get('pageLen','?')} chars)",
            }
        else:
            return {
                "name": f"reject_text({display})",
                "passed": not found,  # Inverted: we want text ABSENT
                "detail": f"'{display}' {'FOUND (BAD)' if found else 'not found (good)'}",
            }
    except json.JSONDecodeError:
        return {"name": "text_check", "passed": False, "detail": f"Parse error: {r['stdout'][:200]}"}


def _check_element(selector, expect_visible=True):
    """Check if an element is visible (or not visible) on the page."""
    if selector.startswith("@"):
        # @ref — use agent-browser's built-in 'is visible'
        r = _run_ab(["is", "visible", selector])
        raw = r["stdout"].strip().lower()
        if r["returncode"] != 0:
            passed = False
        else:
            passed = raw == "true"
    else:
        # CSS selector — use JS eval
        safe_sel = json.dumps(selector)
        js = (
            f"(function(){{"
            f"try{{"
            f"var el=document.querySelector({safe_sel});"
            f"if(!el)return JSON.stringify({{found:false}});"
            f"var s=window.getComputedStyle(el);"
            f"var v=el.offsetWidth>0&&el.offsetHeight>0&&s.visibility!=='hidden'&&s.display!=='none';"
            f"return JSON.stringify({{found:true,visible:v}});"
            f"}}catch(e){{return JSON.stringify({{found:false,error:e.message}});}}"
            f"}})();"
        )
        r = _run_ab_js(js)
        if r["returncode"] != 0:
            passed = False
            detail = f"JS eval failed: {r['stderr']}"
        else:
            try:
                data = json.loads(r["stdout"])
                passed = data.get("visible", False)
                detail = str(data)
            except json.JSONDecodeError:
                passed = False
                detail = f"Parse error: {r['stdout'][:200]}"

    if not expect_visible:
        passed = not passed

    label = "element_match" if expect_visible else f"reject_element({selector})"
    return {"name": label, "passed": passed, "detail": detail if 'detail' in dir() else r.get("stdout", "").strip()}


def _check_js(expression):
    """Evaluate a JS expression — truthy means success."""
    js = (
        f"(function(){{"
        f"try{{"
        f"var r=({expression});"
        f"return JSON.stringify({{value:r,truthy:!!r,type:typeof r}});"
        f"}}catch(e){{return JSON.stringify({{error:e.message}});}}"
        f"}})();"
    )
    r = _run_ab_js(js)
    if r["returncode"] != 0:
        return {"name": "js_match", "passed": False, "detail": f"Eval failed: {r['stderr']}"}

    try:
        data = json.loads(r["stdout"])
        if "error" in data:
            return {"name": "js_match", "passed": False, "detail": f"JS error: {data['error']}"}
        passed = data.get("truthy", False)
        return {
            "name": "js_match",
            "passed": passed,
            "detail": f"Expression truthy={'YES' if passed else 'NO'} (value={json.dumps(data.get('value'))[:100]})",
        }
    except json.JSONDecodeError:
        return {"name": "js_match", "passed": False, "detail": f"Parse error: {r['stdout'][:200]}"}


def cmd_check_completion(args):
    """
    Check if a browser task has completed successfully.

    Runs a battery of checks (URL, text, element, JS expression) and
    returns a structured verdict with confidence level.
    """
    # Wait for page to settle
    if args.wait_ms > 0:
        _run_ab(["wait", str(args.wait_ms)])
    _run_ab(["wait", "--load", "networkidle"])
    _run_ab(["wait", "--load", "domcontentloaded"])

    checks = []
    passed_count = 0
    rejected = False

    # Positive checks (all must pass or majority must pass)
    if args.expect_url:
        c = _check_url(args.expect_url)
        if c["passed"]: passed_count += 1
        checks.append(c)

    if args.expect_text:
        c = _check_text(args.expect_text, expect_present=True)
        if c["passed"]: passed_count += 1
        checks.append(c)

    if args.expect_element:
        c = _check_element(args.expect_element, expect_visible=True)
        if c["passed"]: passed_count += 1
        checks.append(c)

    if args.expect_js:
        c = _check_js(args.expect_js)
        if c["passed"]: passed_count += 1
        checks.append(c)

    # Negative checks (rejection criteria — any hit = task failed)
    if args.reject_text:
        c = _check_text(args.reject_text, expect_present=False)
        if not c["passed"]:
            rejected = True
        checks.append(c)

    if args.reject_element:
        c = _check_element(args.reject_element, expect_visible=False)
        if not c["passed"]:
            rejected = True
        checks.append(c)

    # Compute verdict
    total = len(checks)
    if rejected:
        completed = False
        confidence = "high"
    elif total == 0:
        completed = True
        confidence = "low"
    else:
        ratio = passed_count / total
        completed = ratio >= 0.5
        if ratio >= 0.8:
            confidence = "high"
        elif ratio >= 0.5:
            confidence = "medium"
        else:
            confidence = "low"

    # Get current URL for context
    url_r = _run_ab(["get", "url"])
    current_url = url_r["stdout"].strip() if url_r["returncode"] == 0 else "unknown"

    output = {
        "completed": completed,
        "confidence": confidence,
        "details": {
            "url": current_url,
            "checks_passed": passed_count,
            "checks_total": total,
            "rejected": rejected,
            "checks": checks,
        },
    }

    if args.json:
        return output
    else:
        status = "COMPLETED" if completed else "NOT COMPLETED"
        lines = [
            f"Task Status: {status}",
            f"Confidence:  {confidence}",
            f"URL:         {current_url}",
            f"Checks:      {passed_count}/{total} passed",
        ]
        for c in checks:
            icon = "[PASS]" if c["passed"] else "[FAIL]"
            lines.append(f"  {icon} {c['name']}: {c.get('detail','')}")
        print("\n".join(lines))
        return output


# =============================================================================
# Capability C: Complete Response Content Retrieval
# =============================================================================

# JS snippets for content extraction (stdlib only, no eval of untrusted code)
_EXTRACT_TEXT_JS = """\
(function(){
    var b=document.body;
    if(!b)return'';
    var w=document.createTreeWalker(b,NodeFilter.SHOW_TEXT,null,false);
    var p=[];
    while(w.nextNode()){
        var t=w.currentNode.textContent.replace(/\\s+/g,' ').trim();
        if(t)p.push(t);
    }
    return p.join('\\n');
})();
"""

_EXTRACT_JSON_JS = """\
(function(){
    var d={title:document.title||'',url:location.href||'',meta:{},headings:[],links:[],paragraphs:[],tables:[],lists:[]};
    try{
        document.querySelectorAll('meta').forEach(function(m){
            var n=m.getAttribute('name')||m.getAttribute('property');
            var c=m.getAttribute('content');
            if(n&&c)d.meta[n]=c;
        });
        document.querySelectorAll('h1,h2,h3').forEach(function(h){
            d.headings.push({level:h.tagName,text:h.textContent.trim().substring(0,500)});
        });
        document.querySelectorAll('a[href]').forEach(function(a){
            var href=a.href;
            if(href&&!href.startsWith('javascript:'))
                d.links.push({text:a.textContent.trim().substring(0,200),href:href});
        });
        document.querySelectorAll('p').forEach(function(p){
            var t=p.textContent.trim();
            if(t&&t.length>10)d.paragraphs.push(t.substring(0,2000));
        });
        document.querySelectorAll('table').forEach(function(tbl){
            var rows=[];
            tbl.querySelectorAll('tr').forEach(function(r){
                var cells=[];
                r.querySelectorAll('td,th').forEach(function(c){cells.push(c.textContent.trim())});
                rows.push(cells);
            });
            d.tables.push(rows);
        });
        document.querySelectorAll('ul,ol').forEach(function(l){
            var items=[];
            l.querySelectorAll('li').forEach(function(li){items.push(li.textContent.trim())});
            if(items.length)d.lists.push({type:l.tagName.toLowerCase(),items:items});
        });
    }catch(e){d._error=e.message;}
    return JSON.stringify(d,null,2);
})();
"""


def _scroll_load(max_attempts=10, delay_ms=1500):
    """Scroll to load dynamic/infinite-scroll content. Returns scroll info."""
    js = (
        f"(async function(){{"
        f"var d=function(ms){{return new Promise(function(r){{setTimeout(r,ms)}});}};"
        f"var lastH=0,sameC=0;"
        f"for(var i=0;i<{max_attempts};i++){{"
        f"window.scrollTo(0,document.body.scrollHeight);"
        f"await d({delay_ms});"
        f"var h=document.body.scrollHeight;"
        f"if(h===lastH)sameC++;else sameC=0;"
        f"if(sameC>=3)break;"
        f"lastH=h;"
        f"}}"
        f"return JSON.stringify({{scrolls:i+1,finalHeight:lastH,converged:sameC>=3}});"
        f"}})();"
    )
    r = _run_ab_js(js, timeout=60)
    return r["stdout"] if r["returncode"] == 0 else ""


def _extract_with_js(js_code, timeout=30):
    """Execute extraction JS and parse JSON result (with fallback)."""
    r = _run_ab_js(js_code, timeout=timeout)
    if r["returncode"] != 0:
        return {"_error": r["stderr"], "_raw": r["stdout"]}
    try:
        return json.loads(r["stdout"])
    except (json.JSONDecodeError, TypeError):
        return {"_raw_text": r["stdout"]}


def _save_content(content, output_path=None):
    """Save content to file. Auto-generates temp path if none provided."""
    if output_path:
        path = output_path
        d = os.path.dirname(os.path.abspath(path))
        if d: os.makedirs(d, exist_ok=True)
    else:
        fd, path = tempfile.mkstemp(suffix=".txt", prefix="agent_browser_")
        os.close(fd)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    return path


def _fmt_size(n):
    """Format bytes as human-readable string."""
    if n < 1024:
        return f"{n} B"
    elif n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    else:
        return f"{n / (1024 * 1024):.1f} MB"


def cmd_get_content(args):
    """
    Extract full page content in one of five modes:
      text       — plain visible text (best for reading articles)
      html       — full innerHTML of body
      json       — structured JSON (headings, links, tables, etc.)
      full       — text + accessibility snapshot + JSON
      structured — alias for json
    """
    output = {}

    # Optional: scroll to trigger lazy loading
    if args.scroll:
        info = _scroll_load(args.scroll_max, args.scroll_delay)
        output["scroll_info"] = info.strip()

    # Page metadata
    t = _run_ab(["get", "title"])
    u = _run_ab(["get", "url"])
    metadata = {
        "title": t["stdout"].strip() if t["returncode"] == 0 else "",
        "url": u["stdout"].strip() if u["returncode"] == 0 else "",
    }

    content = ""

    if args.mode == "text":
        extracted = _extract_with_js(_EXTRACT_TEXT_JS, timeout=args.timeout)
        content = extracted.get("_raw_text", "") if "_raw_text" in extracted else (
            str(extracted) if not isinstance(extracted, dict) else json.dumps(extracted, ensure_ascii=False)
        )
        if not content.strip():
            # Fallback: agent-browser get text body
            fb = _run_ab(["get", "text", "body"])
            content = fb["stdout"] if fb["returncode"] == 0 else "(empty page)"

    elif args.mode == "html":
        r = _run_ab(["get", "html", "body"])
        content = r["stdout"] if r["returncode"] == 0 else ""

    elif args.mode in ("json", "structured"):
        extracted = _extract_with_js(_EXTRACT_JSON_JS, timeout=args.timeout)
        content = json.dumps(extracted, ensure_ascii=False, indent=2)

    elif args.mode == "full":
        # Text
        text_extracted = _extract_with_js(_EXTRACT_TEXT_JS, timeout=args.timeout)
        text = text_extracted.get("_raw_text", "") if "_raw_text" in text_extracted else str(text_extracted)

        # Snapshot
        snap_r = _run_ab(["snapshot", "-i", "-c"])
        snapshot = snap_r["stdout"] if snap_r["returncode"] == 0 else "(snapshot failed)"

        # JSON
        json_extracted = _extract_with_js(_EXTRACT_JSON_JS, timeout=args.timeout)
        json_str = json.dumps(json_extracted, ensure_ascii=False, indent=2)

        content = "\n".join([
            "=" * 60,
            "METADATA",
            "=" * 60,
            f"Title: {metadata['title']}",
            f"URL:   {metadata['url']}",
            "",
            "=" * 60,
            "ACCESSIBILITY SNAPSHOT (interactive elements)",
            "=" * 60,
            snapshot,
            "",
            "=" * 60,
            "FULL TEXT CONTENT",
            "=" * 60,
            text,
            "",
            "=" * 60,
            "STRUCTURED DATA (JSON)",
            "=" * 60,
            json_str,
        ])

    # Size check and output routing
    size_bytes = len(content.encode("utf-8"))
    output["metadata"] = metadata
    output["size_bytes"] = size_bytes
    output["size_human"] = _fmt_size(size_bytes)

    if args.output:
        path = _save_content(content, args.output)
        output["output_path"] = path
        output["message"] = f"Saved to {path} ({_fmt_size(size_bytes)})"
        output["content_preview"] = content[:1500] + "\n\n... (see file for full content)"
    elif size_bytes > CONTENT_WARN_THRESHOLD:
        path = _save_content(content)
        output["output_path"] = path
        output["message"] = (
            f"Content is {_fmt_size(size_bytes)} — auto-saved to {path} to avoid shell truncation."
        )
        output["content_preview"] = content[:1500] + "\n\n... (see file for full content)"
    else:
        output["content"] = content

    if args.json:
        return output
    else:
        lines = [
            f"Title: {metadata['title']}",
            f"URL:   {metadata['url']}",
            f"Size:  {output['size_human']}",
        ]
        if "output_path" in output:
            lines.append(f"Saved: {output['output_path']}")
            lines.append("")
            lines.append(output.get("content_preview", ""))
        else:
            lines.append("")
            lines.append(output.get("content", ""))
        print("\n".join(lines))
        return output


# =============================================================================
# Convenience: extract-all (navigate + wait + scroll + extract in one shot)
# =============================================================================

def cmd_extract_all(args):
    """Navigate to a URL, wait for load, optionally scroll, then extract content."""
    # Navigate
    nav = _run_ab(["open", args.url])
    if nav["returncode"] != 0:
        return _error(f"Navigation failed: {nav['stderr']}")

    # Wait
    _run_ab(["wait", "--load", "networkidle"])

    # Scroll
    if args.scroll:
        _scroll_load(args.scroll_max, args.scroll_delay)

    # Extract
    extract_args = argparse.Namespace(
        mode=args.mode,
        scroll=False,
        scroll_max=args.scroll_max,
        scroll_delay=args.scroll_delay,
        output=args.output,
        timeout=args.timeout,
        json=args.json,
    )
    return cmd_get_content(extract_args)


# =============================================================================
# Helpers
# =============================================================================

def _error(msg):
    return {"error": msg, "success": False}


# =============================================================================
# CLI Parser
# =============================================================================

def _build_parser():
    parser = argparse.ArgumentParser(
        prog="agent_browser_helper.py",
        description="Enhanced agent-browser CLI wrapper with 3 superpowers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Cap A — Execute multi-line JS from a file
  python agent_browser_helper.py eval-js script.js

  # Cap A — Execute base64-encoded JS
  python agent_browser_helper.py eval-js --base64 ZG9jdW1lbnQudGl0bGU=

  # Cap B — Verify login succeeded
  python agent_browser_helper.py check-completion \\
      --expect-url "**/dashboard" --expect-text "Welcome" --json

  # Cap C — Extract full page as structured JSON
  python agent_browser_helper.py get-content --mode json --output page.json

  # One-shot: navigate + extract
  python agent_browser_helper.py extract-all "https://example.com" --mode text
        """,
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # ---- eval-js (Cap A) ----
    p_eval = sub.add_parser("eval-js", help="Execute JavaScript in browser (no shell escaping)")
    p_eval.add_argument("file", nargs="?", help="Path to JavaScript file")
    p_eval.add_argument("--base64", help="Base64-encoded JavaScript string")
    p_eval.add_argument("--json", action="store_true", help="Parse JSON output from eval")
    p_eval.add_argument("--timeout", type=int, default=30, help="Timeout in seconds (default: 30)")

    # ---- check-completion (Cap B) ----
    p_check = sub.add_parser("check-completion", help="Verify if a browser task completed")
    p_check.add_argument("--expect-url", help="Expected URL glob pattern (e.g. '**/dashboard')")
    p_check.add_argument("--expect-text", help="Expected text to be present on page")
    p_check.add_argument("--expect-element", help="Expected CSS selector or @ref to be visible")
    p_check.add_argument("--expect-js", help="JS expression that should evaluate to truthy")
    p_check.add_argument("--reject-text", help="Text whose presence indicates FAILURE")
    p_check.add_argument("--reject-element", help="Element whose visibility indicates FAILURE")
    p_check.add_argument("--wait-ms", type=int, default=DEFAULT_WAIT_MS,
                         help=f"Wait before checks in ms (default: {DEFAULT_WAIT_MS})")
    p_check.add_argument("--json", action="store_true", help="Output structured JSON")

    # ---- get-content (Cap C) ----
    p_content = sub.add_parser("get-content", help="Extract full page content")
    p_content.add_argument("--mode", choices=["text", "html", "json", "full", "structured"],
                           default="text", help="Extraction mode (default: text)")
    p_content.add_argument("--output", help="Save content to file path")
    p_content.add_argument("--scroll", action="store_true", help="Scroll to trigger lazy-loading")
    p_content.add_argument("--scroll-max", type=int, default=10, help="Max scroll iterations (default: 10)")
    p_content.add_argument("--scroll-delay", type=int, default=1500, help="Delay between scrolls in ms (default: 1500)")
    p_content.add_argument("--timeout", type=int, default=30, help="JS execution timeout (default: 30)")
    p_content.add_argument("--json", action="store_true", help="Output structured JSON")

    # ---- extract-all (convenience) ----
    p_extract = sub.add_parser("extract-all", help="Navigate to URL and extract content in one step")
    p_extract.add_argument("url", help="URL to navigate to")
    p_extract.add_argument("--mode", choices=["text", "html", "json", "full", "structured"],
                           default="text", help="Extraction mode (default: text)")
    p_extract.add_argument("--output", help="Save content to file path")
    p_extract.add_argument("--scroll", action="store_true", help="Scroll to trigger lazy-loading")
    p_extract.add_argument("--scroll-max", type=int, default=10, help="Max scroll iterations")
    p_extract.add_argument("--scroll-delay", type=int, default=1500, help="Scroll delay in ms")
    p_extract.add_argument("--timeout", type=int, default=60, help="Timeout in seconds (default: 60)")
    p_extract.add_argument("--json", action="store_true", help="Output structured JSON")

    return parser


# =============================================================================
# Main
# =============================================================================

def main():
    parser = _build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Route to handler
    handlers = {
        "eval-js": cmd_eval_js,
        "check-completion": cmd_check_completion,
        "get-content": cmd_get_content,
        "extract-all": cmd_extract_all,
    }

    handler = handlers.get(args.command)
    if not handler:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)

    result = handler(args)

    # Print JSON output (for --json mode or structured results)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # Exit code
    if isinstance(result, dict):
        if result.get("error") or result.get("success") is False:
            sys.exit(1)
        if result.get("completed") is False:
            sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
