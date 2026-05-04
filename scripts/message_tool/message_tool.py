#!/usr/bin/env python3
"""message_tool — Compose-once, format-many message pipeline for DIL.

Python core. Bash and PowerShell wrappers call this.
Persistent drafts in _shared/signals/drafts/. Nozzle rendering. Multi-channel dispatch.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Nozzle imports — resolved at runtime from scripts library or DIL
NOZZLE_PATHS = []


def resolve_base_dil():
    base = os.environ.get("BASE_DIL")
    if base and os.path.isdir(base):
        return base
    script_dir = Path(__file__).resolve().parent
    candidate = script_dir.parent.parent.parent
    if (candidate / "READ_THIS_DIL_FIRST.md").is_file():
        return str(candidate)
    fallback = Path.home() / "Documents" / "dil_agentic_memory_0001"
    if fallback.is_dir():
        return str(fallback)
    print("ERROR: Cannot resolve BASE_DIL", file=sys.stderr)
    sys.exit(1)


def resolve_identity(base_dil):
    try:
        machine = subprocess.check_output(
            ["hostname", "-s"], stderr=subprocess.DEVNULL, text=True
        ).strip().lower()
    except Exception:
        machine = os.environ.get("HOSTNAME", "unknown").split(".")[0].lower()
    agent_script = os.path.join(base_dil, "_shared", "scripts", "identify_agent.sh")
    assistant = "unknown"
    if os.path.isfile(agent_script):
        try:
            assistant = subprocess.check_output(
                [agent_script], stderr=subprocess.DEVNULL, text=True
            ).strip()
        except Exception:
            pass
    if not assistant or assistant == "UNRESOLVED":
        assistant = os.environ.get("ASSISTANT_ID", os.environ.get("AGENT_NAME", "unknown"))
    return f"{assistant}@{machine}"


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_file_timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def drafts_dir(base_dil):
    d = os.path.join(base_dil, "_shared", "signals", "drafts")
    os.makedirs(d, exist_ok=True)
    return d


def load_nozzles(base_dil):
    """Find and import nozzle library from scripts library or DIL."""
    candidates = [
        os.path.join(base_dil, "_shared", "scripts", "lib"),
        "/org/platform/scripts/python/lib",
    ]
    for p in candidates:
        if os.path.isdir(os.path.join(p, "nozzles")):
            if p not in sys.path:
                sys.path.insert(0, p)
            return True
    return False


def get_nozzle(nozzle_name):
    """Return a nozzle formatter instance by name."""
    try:
        if nozzle_name == "html":
            from nozzles.html import HtmlFormatter
            return HtmlFormatter()
        elif nozzle_name == "jira":
            from nozzles.jira import JiraFormatter
            return JiraFormatter()
        elif nozzle_name == "email":
            from nozzles.email import EmailFormatter
            return EmailFormatter()
        elif nozzle_name == "text":
            from nozzles.text import TextFormatter
            return TextFormatter()
        elif nozzle_name == "github":
            from nozzles.github import GitHubFormatter
            return GitHubFormatter()
        elif nozzle_name == "teams":
            from nozzles.html import HtmlFormatter
            return HtmlFormatter()
        elif nozzle_name == "xpost":
            from nozzles.xpost import XPostFormatter
            return XPostFormatter()
        else:
            from nozzles.text import TextFormatter
            return TextFormatter()
    except ImportError:
        return None


def default_nozzle_for_channel(channel):
    """Map channel to default nozzle."""
    return {
        "teams": "html",
        "email": "html",
        "jira": "jira",
        "x-dm": "text",
        "x-post": "xpost",
        "github": "github",
        "text": "text",
        "stdout": "text",
    }.get(channel, "text")


def parse_draft(path):
    """Parse a draft file with YAML-like frontmatter + body.
    Handles emissions[] as a JSON array stored in a single frontmatter line.
    """
    with open(path) as f:
        content = f.read()
    meta = {}
    emissions = []
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split("\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if key == "emissions":
                        try:
                            emissions = json.loads(val) if val else []
                        except json.JSONDecodeError:
                            emissions = []
                    else:
                        meta[key.strip()] = val
            body = parts[2].strip()
    meta["_emissions"] = emissions
    return meta, body


def write_draft(path, meta, body):
    """Write a draft file with frontmatter + body.
    Emissions stored as JSON array for machine readability.
    """
    emissions = meta.pop("_emissions", [])
    with open(path, "w") as f:
        f.write("---\n")
        for k, v in meta.items():
            f.write(f"{k}: {v}\n")
        if emissions:
            f.write(f"emissions: {json.dumps(emissions)}\n")
        f.write("---\n\n")
        f.write(body)
        f.write("\n")
    meta["_emissions"] = emissions


def add_emission(meta, channel, nozzle_name, method, to="", extra=None):
    """Append an emission record to the draft metadata."""
    emission = {
        "channel": channel,
        "nozzle": nozzle_name,
        "sent_at": now_utc(),
        "method": method,
        "status": "sent",
    }
    if to:
        emission["to"] = to
    if extra:
        emission.update(extra)
    if "_emissions" not in meta:
        meta["_emissions"] = []
    meta["_emissions"].append(emission)
    return emission


def find_latest_draft(drafts):
    """Find the most recent draft file."""
    files = sorted(Path(drafts).glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(files[0]) if files else None


def find_draft_by_id(drafts, draft_id):
    """Find a draft by partial ID match."""
    for f in Path(drafts).glob("*.md"):
        if draft_id in f.name:
            return str(f)
    return None


def render_body(body, nozzle_name, base_dil):
    """Render body text through a nozzle."""
    load_nozzles(base_dil)
    nozzle = get_nozzle(nozzle_name)
    if not nozzle:
        return body

    lines = body.split("\n")
    rendered = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            rendered.append(nozzle.spacer() if hasattr(nozzle, "spacer") else "")
        elif stripped.startswith("# "):
            rendered.append(nozzle.title(stripped[2:]))
        elif stripped.startswith("## "):
            rendered.append(nozzle.header(stripped[3:]))
        elif stripped.startswith("### "):
            rendered.append(nozzle.subheader(stripped[4:]))
        elif stripped.startswith("- "):
            rendered.append(nozzle.bullet(stripped[2:]))
        elif re.match(r"^\d+\.\s", stripped):
            num, text = stripped.split(".", 1)
            rendered.append(nozzle.numbered(int(num), text.strip()))
        else:
            if nozzle_name in ("html", "teams", "email"):
                rendered.append(f"<p>{stripped}</p>")
            else:
                rendered.append(stripped)
    return "\n".join(rendered)


def copy_to_clipboard(text, content_type="text/html"):
    """Copy to clipboard via wl-copy, with CopyQ and xclip fallbacks."""
    for cmd in [
        ["wl-copy", "--type", content_type],
        ["xclip", "-selection", "clipboard"],
    ]:
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            proc.communicate(input=text.encode())
            if proc.returncode == 0:
                return True
        except FileNotFoundError:
            continue
    return False


def dispatch_teams(body, rendered_html):
    """Dispatch a message to Teams via CDP.

    Strategy:
    1. Try clipboard paste (wl-copy HTML → Ctrl+V) — best formatting
    2. Fallback: output JSON CDP sequence for the agent to execute

    Returns dispatch method used and optionally the CDP sequence.
    """
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]

    # Strategy 1: clipboard
    if copy_to_clipboard(rendered_html, "text/html"):
        print("OK | HTML copied to clipboard")
        print("DISPATCH | Ctrl+V into Teams compose box, then Ctrl+Enter to send")
        return "clipboard"

    # Strategy 2: output CDP sequence as JSON for agent execution
    print("WARN | clipboard unavailable, outputting CDP sequence")
    return "cdp_sequence"


def get_cdp_sequence(draft_path):
    """Return a JSON array of CDP commands for paragraph-aware Teams dispatch.

    The agent reads this and executes each command in order.
    """
    _, body = parse_draft(draft_path)
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]

    commands = []
    for i, para in enumerate(paragraphs):
        commands.append({"action": "type_text", "text": para})
        if i < len(paragraphs) - 1:
            commands.append({"action": "press_key", "key": "Shift+Enter"})
            commands.append({"action": "press_key", "key": "Shift+Enter"})
    commands.append({"action": "press_key", "key": "Control+Enter"})
    return commands


def dispatch_email(body, rendered_html, meta, base_dil):
    """Dispatch a message via email (himalaya / mail_tool)."""
    to = meta.get("to", "")
    subject = meta.get("subject", "")

    # Build raw email
    from_addr = "maintainer@example.com"  # TODO: resolve from config
    email_content = f"""From: {from_addr}
To: {to}
Subject: {subject}
Content-Type: text/html; charset=utf-8

{rendered_html}
"""
    # Try mail_tool first, then himalaya directly
    for tool in [
        os.path.join(base_dil, "_shared", "scripts", "mail_tool"),
        "/org/platform/scripts/bin/mail_tool",
    ]:
        if os.path.isfile(tool) and os.access(tool, os.X_OK):
            try:
                result = subprocess.run(
                    [tool, "send", "--to", to, "--subject", subject],
                    input=rendered_html, capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0:
                    print(f"OK | email sent via mail_tool to {to}")
                    return "mail_tool"
            except Exception:
                pass

    # Fallback: himalaya directly
    try:
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".eml", delete=False) as f:
            f.write(email_content)
            tmp_path = f.name
        result = subprocess.run(
            ["himalaya", "message", "send", "--account", "maintainer"],
            stdin=open(tmp_path), capture_output=True, text=True, timeout=30,
        )
        os.unlink(tmp_path)
        if "successfully" in result.stdout.lower() or result.returncode == 0:
            # Verify in Sent folder
            verify = subprocess.run(
                ["himalaya", "envelope", "list", "--account", "maintainer",
                 "--folder", "[Gmail]/Sent Mail", "--page-size", "1"],
                capture_output=True, text=True, timeout=15,
            )
            print(f"OK | email sent via himalaya to {to}")
            if verify.stdout:
                latest = verify.stdout.strip().split("\n")[-1]
                print(f"VERIFY | Sent folder: {latest}")
            return "himalaya"
        else:
            print(f"ERROR | himalaya send failed: {result.stderr}", file=sys.stderr)
            return "failed"
    except Exception as e:
        print(f"ERROR | email dispatch failed: {e}", file=sys.stderr)
        return "failed"


def get_x_post_cdp_sequence(draft_path, mode="preview"):
    """Return a JSON array of CDP commands for X posting.

    Modes:
      preview  — navigate, paste, screenshot. Stop before posting.
      confirm  — navigate, paste, screenshot, then click Post (agent confirms first).
      auto     — navigate, paste, click Post, screenshot result.
    """
    meta, body = parse_draft(draft_path)
    reply_to = ""
    subject = meta.get("subject", "")
    if subject.startswith("reply-to:"):
        reply_to = subject.split(":", 1)[1].strip()

    if reply_to:
        url = f"https://x.com/i/status/{reply_to}"
    else:
        url = "https://x.com/compose/post"

    commands = [
        {"action": "navigate", "url": url},
        {"action": "wait", "ms": 2000},
        {"action": "clipboard", "text": body, "content_type": "text/plain"},
    ]

    if reply_to:
        commands.append({"action": "click", "target": "reply_compose_area"})
        commands.append({"action": "wait", "ms": 500})

    commands.append({"action": "press_key", "key": "Control+v"})
    commands.append({"action": "wait", "ms": 500})
    commands.append({"action": "screenshot", "label": "pre_post_verify"})

    if mode == "auto":
        commands.append({"action": "click", "target": "post_button"})
        commands.append({"action": "wait", "ms": 2000})
        commands.append({"action": "screenshot", "label": "post_confirm"})
    elif mode == "confirm":
        commands.append({"action": "confirm", "prompt": "Post this to X?"})
        commands.append({"action": "click", "target": "post_button"})
        commands.append({"action": "wait", "ms": 2000})
        commands.append({"action": "screenshot", "label": "post_confirm"})

    return commands


def dispatch_x_post(body, rendered, mode="preview", draft_path=None):
    """Dispatch an X post via clipboard + CDP sequence.

    Modes:
      preview  — copy to clipboard, output CDP sequence, stop before Post.
      confirm  — copy to clipboard, CDP sequence includes Post after confirmation.
      auto     — copy to clipboard, CDP sequence posts without gate.
    """
    load_nozzles(resolve_base_dil())
    nozzle = get_nozzle("xpost")
    if nozzle and hasattr(nozzle, "count_chars"):
        char_count = nozzle.count_chars(rendered)
        if char_count > 280:
            print(
                f"WARN | {char_count} chars exceeds 280 limit (over by {char_count - 280})",
                file=sys.stderr,
            )
        else:
            print(f"OK | {char_count}/280 chars")

    if not copy_to_clipboard(rendered, "text/plain"):
        print("WARN | clipboard unavailable, outputting to stdout")
        print(rendered)
        return "stdout"

    print("OK | post text copied to clipboard (text/plain)")

    if draft_path:
        cdp_seq = get_x_post_cdp_sequence(draft_path, mode=mode)
        print(f"CDP_SEQUENCE | {json.dumps(cdp_seq)}")

    mode_label = {"preview": "paste only — verify then post manually",
                  "confirm": "paste + confirm before posting",
                  "auto": "paste + post (no gate)"}
    print(f"DISPATCH | mode={mode} | {mode_label.get(mode, mode)}")
    return f"clipboard+cdp:{mode}"


def dispatch_jira(body, meta, base_dil):
    """Dispatch a message as a Jira comment."""
    to = meta.get("to", "")  # ticket ID
    load_nozzles(base_dil)
    jira_rendered = render_body(body, "jira", base_dil)

    jira_tool = "/org/platform/scripts/bin/jira_tool"
    if not os.path.isfile(jira_tool):
        jira_tool = os.path.join(base_dil, "_shared", "scripts", "jira_tool")

    if not os.path.isfile(jira_tool):
        print(f"ERROR | jira_tool not found", file=sys.stderr)
        print(jira_rendered)
        return "failed"

    try:
        result = subprocess.run(
            [jira_tool, "comment", to, jira_rendered],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout.strip()
        print(output)
        comment_id = ""
        if "comment" in output:
            parts = output.split("comment")
            if len(parts) > 1:
                comment_id = parts[-1].strip()
        return comment_id or "sent"
    except Exception as e:
        print(f"ERROR | jira comment failed: {e}", file=sys.stderr)
        return "failed"


def log_to_signal_ledger(base_dil, self_id, to, subject, channel):
    """Log the send to the signal ledger via signal_tool."""
    signal_tool = os.path.join(base_dil, "_shared", "scripts", "signal_tool")
    if os.path.isfile(signal_tool):
        try:
            subprocess.run(
                [signal_tool, "send", "--to", to, "--subject", subject, "--channel", channel],
                env={**os.environ, "BASE_DIL": base_dil},
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass


# === Commands ===


def cmd_compose(args):
    base_dil = resolve_base_dil()
    self_id = resolve_identity(base_dil)
    drafts = drafts_dir(base_dil)
    ts = now_file_timestamp()
    channel = args.channel or "teams"
    nozzle = args.nozzle or default_nozzle_for_channel(channel)
    to_clean = re.sub(r"[^a-zA-Z0-9_-]", "_", args.to)
    filename = f"{ts}_{to_clean}_{channel}.md"
    path = os.path.join(drafts, filename)

    body = ""
    if args.body:
        body = args.body
    elif args.file:
        with open(args.file) as f:
            body = f.read()
    elif not sys.stdin.isatty():
        body = sys.stdin.read()
    else:
        body = ""

    meta = {
        "to": args.to,
        "from": self_id,
        "channel": channel,
        "subject": args.subject or "",
        "nozzle": nozzle,
        "status": "draft",
        "created": now_utc(),
        "sent_at": "",
        "message_id": "",
    }
    write_draft(path, meta, body)

    if args.json:
        print(json.dumps({"path": path, **meta}))
    else:
        print(f"OK | draft created | {path}")
        if body:
            print(f"     to: {args.to} | channel: {channel} | nozzle: {nozzle}")


def cmd_format(args):
    base_dil = resolve_base_dil()
    drafts = drafts_dir(base_dil)

    path = args.draft or find_latest_draft(drafts)
    if not path or not os.path.isfile(path):
        if args.draft:
            path = find_draft_by_id(drafts, args.draft)
        if not path:
            print("No draft found.", file=sys.stderr)
            sys.exit(1)

    meta, body = parse_draft(path)
    nozzle_name = args.nozzle or meta.get("nozzle", "text")
    rendered = render_body(body, nozzle_name, base_dil)

    if args.clipboard:
        content_type = "text/html" if nozzle_name in ("html", "teams", "email") else "text/plain"
        if copy_to_clipboard(rendered, content_type):
            print(f"OK | copied to clipboard ({content_type})")
        else:
            print("WARN | clipboard copy failed — outputting to stdout", file=sys.stderr)
            print(rendered)
    else:
        print(rendered)


def cmd_edit(args):
    base_dil = resolve_base_dil()
    drafts = drafts_dir(base_dil)

    path = args.draft or find_latest_draft(drafts)
    if not path or not os.path.isfile(path):
        if args.draft:
            path = find_draft_by_id(drafts, args.draft)
        if not path:
            print("No draft found.", file=sys.stderr)
            sys.exit(1)

    meta, old_body = parse_draft(path)

    if args.body:
        new_body = args.body
    elif args.file:
        with open(args.file) as f:
            new_body = f.read()
    elif not sys.stdin.isatty():
        new_body = sys.stdin.read()
    else:
        print(f"Current draft: {path}", file=sys.stderr)
        print(old_body)
        return

    if args.append:
        new_body = old_body + "\n\n" + new_body

    write_draft(path, meta, new_body)
    print(f"OK | draft updated | {path}")


def cmd_send(args):
    base_dil = resolve_base_dil()
    self_id = resolve_identity(base_dil)
    drafts = drafts_dir(base_dil)

    path = args.draft or find_latest_draft(drafts)
    if not path or not os.path.isfile(path):
        if args.draft:
            path = find_draft_by_id(drafts, args.draft)
        if not path:
            print("No draft found.", file=sys.stderr)
            sys.exit(1)

    meta, body = parse_draft(path)
    channel = args.channel or meta.get("channel", "text")
    nozzle_name = args.nozzle or meta.get("nozzle", default_nozzle_for_channel(channel))
    rendered = render_body(body, nozzle_name, base_dil)
    to = args.to or meta.get("to", "")
    subject = meta.get("subject", "")

    dispatch_result = "unknown"

    if channel == "x-post":
        x_mode = getattr(args, "x_mode", "preview")
        dispatch_result = dispatch_x_post(body, rendered, mode=x_mode, draft_path=path)
        method = dispatch_result if dispatch_result != "stdout" else "stdout"
        add_emission(meta, channel, nozzle_name, method)

    elif channel in ("teams", "x-dm"):
        dispatch_result = dispatch_teams(body, rendered)
        method = "wl-copy" if dispatch_result == "clipboard" else "cdp_sequence"
        add_emission(meta, channel, nozzle_name, method)

    elif channel == "email":
        dispatch_result = dispatch_email(body, rendered, meta, base_dil)
        add_emission(meta, channel, nozzle_name, dispatch_result, to=to)

    elif channel == "jira":
        dispatch_result = dispatch_jira(body, meta, base_dil)
        extra = {"comment_id": dispatch_result} if dispatch_result not in ("sent", "failed") else None
        add_emission(meta, channel, "jira", "jira_tool comment", to=to, extra=extra)

    else:
        add_emission(meta, channel, nozzle_name, "stdout")
        print(rendered)
        dispatch_result = "stdout"

    # Update draft status
    meta["status"] = "sent" if dispatch_result != "failed" else "failed"
    meta["sent_at"] = now_utc()
    write_draft(path, meta, body)

    # Log to signal ledger
    log_to_signal_ledger(base_dil, self_id, to, subject, channel)

    if args.json:
        print(json.dumps({"status": meta["status"], "channel": channel, "to": to, "dispatch": dispatch_result, "path": path}))


def cmd_resend(args):
    base_dil = resolve_base_dil()
    drafts = drafts_dir(base_dil)

    path = args.draft or find_latest_draft(drafts)
    if not path or not os.path.isfile(path):
        if args.draft:
            path = find_draft_by_id(drafts, args.draft)
        if not path:
            print("No draft found.", file=sys.stderr)
            sys.exit(1)

    meta, body = parse_draft(path)
    nozzle_name = args.nozzle or meta.get("nozzle", "text")
    rendered = render_body(body, nozzle_name, base_dil)

    content_type = "text/html" if nozzle_name in ("html", "teams", "email") else "text/plain"
    if copy_to_clipboard(rendered, content_type):
        print(f"OK | re-copied to clipboard ({content_type})")
    else:
        print("WARN | clipboard failed — output below:", file=sys.stderr)
        print(rendered)


def cmd_list(args):
    base_dil = resolve_base_dil()
    drafts = drafts_dir(base_dil)
    files = sorted(Path(drafts).glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not files:
        print("No drafts.")
        return

    limit = args.limit or 10
    rows = []
    for f in files[:limit]:
        meta, _ = parse_draft(str(f))
        rows.append({
            "file": f.name,
            "to": meta.get("to", ""),
            "channel": meta.get("channel", ""),
            "status": meta.get("status", ""),
            "subject": meta.get("subject", "")[:50],
            "created": meta.get("created", ""),
        })

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print(f"{'file':<45}  {'to':<15}  {'channel':<8}  {'status':<7}  subject")
        print("-" * 110)
        for r in rows:
            print(f"{r['file']:<45}  {r['to']:<15}  {r['channel']:<8}  {r['status']:<7}  {r['subject']}")


def cmd_show(args):
    base_dil = resolve_base_dil()
    drafts = drafts_dir(base_dil)

    path = args.draft or find_latest_draft(drafts)
    if not path or not os.path.isfile(path):
        if args.draft:
            path = find_draft_by_id(drafts, args.draft)
        if not path:
            print("No draft found.", file=sys.stderr)
            sys.exit(1)

    meta, body = parse_draft(path)

    if args.json:
        print(json.dumps({"path": path, "meta": meta, "body": body}, indent=2))
    else:
        print(f"Draft: {path}")
        print("-" * 60)
        for k, v in meta.items():
            print(f"  {k}: {v}")
        print("-" * 60)
        print(body)


def main():
    parser = argparse.ArgumentParser(
        description="message_tool — compose-once, format-many message pipeline",
        epilog=(
            "All agent-composed prose (internal or external) must use this tool.\n"
            "Compose in _shared/messages/, format through nozzles, deliver to any channel.\n"
            "Message files are cross-session thinking artifacts — any agent can discover,\n"
            "resume, or build on composed thought from another session or agent.\n\n"
            "Contract: _shared/messages/CONTRACT.md\n"
            "Policy:   _shared/policies/compose-via-message-contract-2026-05-02.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    sub = parser.add_subparsers(dest="command")

    p_compose = sub.add_parser("compose", help="Create a new draft message")
    p_compose.add_argument("--to", required=True, help="Recipient (name, email, ticket ID)")
    p_compose.add_argument("--channel", default="teams", choices=["teams", "email", "jira", "x-dm", "x-post", "github", "text", "stdout"])
    p_compose.add_argument("--subject", default="", help="Message subject")
    p_compose.add_argument("--nozzle", default="", help="Override nozzle (html, jira, email, text, github)")
    p_compose.add_argument("--body", default="", help="Message body (or pipe via stdin)")
    p_compose.add_argument("--file", default="", help="Read body from file")

    p_format = sub.add_parser("format", help="Render a draft through a nozzle")
    p_format.add_argument("draft", nargs="?", default="", help="Draft file path or ID (default: latest)")
    p_format.add_argument("--nozzle", default="", help="Override nozzle")
    p_format.add_argument("--clipboard", action="store_true", help="Copy rendered output to clipboard")

    p_edit = sub.add_parser("edit", help="Edit a draft's body")
    p_edit.add_argument("draft", nargs="?", default="", help="Draft file path or ID (default: latest)")
    p_edit.add_argument("--body", default="", help="New body text")
    p_edit.add_argument("--file", default="", help="Read new body from file")
    p_edit.add_argument("--append", action="store_true", help="Append instead of replace")

    p_send = sub.add_parser("send", help="Dispatch a draft to its channel")
    p_send.add_argument("draft", nargs="?", default="", help="Draft file path or ID (default: latest)")
    p_send.add_argument("--channel", default="", help="Override channel for this emission")
    p_send.add_argument("--nozzle", default="", help="Override nozzle for this emission")
    p_send.add_argument("--to", default="", help="Override recipient for this emission")
    p_send.add_argument("--x-mode", default="preview", choices=["preview", "confirm", "auto"],
                        dest="x_mode",
                        help="X post dispatch mode: preview (paste+stop), confirm (paste+ask+post), auto (paste+post)")

    p_resend = sub.add_parser("resend", help="Re-copy a draft to clipboard")
    p_resend.add_argument("draft", nargs="?", default="", help="Draft file path or ID (default: latest)")
    p_resend.add_argument("--nozzle", default="", help="Override nozzle")

    p_list = sub.add_parser("list", help="List draft messages")
    p_list.add_argument("--limit", type=int, default=10)

    p_show = sub.add_parser("show", help="Show a draft message")
    p_show.add_argument("draft", nargs="?", default="", help="Draft file path or ID (default: latest)")

    p_cdp = sub.add_parser("cdp-sequence", help="Output CDP command sequence for Teams dispatch")
    p_cdp.add_argument("draft", nargs="?", default="", help="Draft file path or ID (default: latest)")

    p_xcdp = sub.add_parser("x-cdp-sequence", help="Output CDP command sequence for X post dispatch")
    p_xcdp.add_argument("draft", nargs="?", default="", help="Draft file path or ID (default: latest)")
    p_xcdp.add_argument("--mode", default="preview", choices=["preview", "confirm", "auto"],
                         help="preview (paste+stop), confirm (paste+ask+post), auto (paste+post)")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    def cmd_cdp_sequence(args):
        base_dil = resolve_base_dil()
        d = drafts_dir(base_dil)
        path = args.draft or find_latest_draft(d)
        if not path or not os.path.isfile(path):
            if args.draft:
                path = find_draft_by_id(d, args.draft)
            if not path:
                print("No draft found.", file=sys.stderr)
                sys.exit(1)
        commands = get_cdp_sequence(path)
        print(json.dumps(commands, indent=2))

    def cmd_x_cdp_sequence(args):
        base_dil = resolve_base_dil()
        d = drafts_dir(base_dil)
        path = args.draft or find_latest_draft(d)
        if not path or not os.path.isfile(path):
            if args.draft:
                path = find_draft_by_id(d, args.draft)
            if not path:
                print("No draft found.", file=sys.stderr)
                sys.exit(1)
        commands = get_x_post_cdp_sequence(path, mode=args.mode)
        print(json.dumps(commands, indent=2))

    dispatch = {
        "compose": cmd_compose,
        "format": cmd_format,
        "edit": cmd_edit,
        "send": cmd_send,
        "resend": cmd_resend,
        "list": cmd_list,
        "show": cmd_show,
        "cdp-sequence": cmd_cdp_sequence,
        "x-cdp-sequence": cmd_x_cdp_sequence,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
