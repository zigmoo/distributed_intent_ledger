"""
DIL ingestion adapter for URLs requiring browser rendering.

Uses Chrome DevTools Protocol (CDP) via stdlib-only websocket client
to render JS-heavy pages (X/Twitter, Reddit, etc.) and extract content.
Requires Chrome/Chromium running with --remote-debugging-port=9222.

Falls back to static HTML parsing for sites that don't need JS rendering.
"""

import json
import os
import socket
import struct
import base64
import time
import urllib.request
import urllib.error
import re
from datetime import datetime, timezone

# Domains that require browser rendering (JS-rendered SPAs)
BROWSER_REQUIRED_DOMAINS = {
    "x.com", "twitter.com",
    "reddit.com", "www.reddit.com",
    "linkedin.com", "www.linkedin.com",
}

CDP_HOST = "localhost"
CDP_PORT = 9222
CDP_TIMEOUT = 20  # seconds to wait for page render


# ---------------------------------------------------------------------------
# Minimal stdlib-only WebSocket client
# ---------------------------------------------------------------------------

class _WebSocket:
    """Minimal WebSocket client using only stdlib (socket + struct)."""

    def __init__(self, host, port, path):
        self.sock = socket.create_connection((host, port), timeout=CDP_TIMEOUT)
        self.sock.settimeout(CDP_TIMEOUT)
        key = base64.b64encode(os.urandom(16)).decode()
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        self.sock.sendall(handshake.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket handshake failed: connection closed")
            response += chunk
        if b"101" not in response:
            raise ConnectionError(f"WebSocket handshake failed: {response[:200].decode(errors='replace')}")

    def send(self, data):
        payload = data.encode()
        frame = bytearray()
        frame.append(0x81)  # text frame, FIN
        mask_key = os.urandom(4)
        length = len(payload)
        if length < 126:
            frame.append(0x80 | length)
        elif length < 65536:
            frame.append(0x80 | 126)
            frame.extend(struct.pack(">H", length))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack(">Q", length))
        frame.extend(mask_key)
        masked = bytearray(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        frame.extend(masked)
        self.sock.sendall(frame)

    def recv(self, max_size=4 * 1024 * 1024):
        """Receive a complete WebSocket frame. Handles fragmentation."""
        data = b""
        while True:
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                raise TimeoutError("WebSocket recv timed out")
            if not chunk:
                raise ConnectionError("WebSocket connection closed")
            data += chunk
            if len(data) < 2:
                continue
            length = data[1] & 0x7f
            offset = 2
            if length == 126:
                if len(data) < 4:
                    continue
                length = struct.unpack(">H", data[2:4])[0]
                offset = 4
            elif length == 127:
                if len(data) < 10:
                    continue
                length = struct.unpack(">Q", data[2:10])[0]
                offset = 10
            masked = (data[1] & 0x80) != 0
            if masked:
                offset += 4
            if len(data) >= offset + length:
                payload = data[offset:offset + length]
                return payload.decode("utf-8", errors="replace")
            if len(data) > max_size:
                raise ValueError("WebSocket frame too large")

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CDP helpers
# ---------------------------------------------------------------------------

def _cdp_available():
    """Check if Chrome DevTools Protocol is available."""
    try:
        resp = urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json/version", timeout=3)
        return resp.status == 200
    except Exception:
        return False


def _cdp_new_tab(url):
    """Create a new tab via CDP HTTP API. Returns tab info dict."""
    encoded = urllib.parse.quote(url, safe=":/?&=#")
    req = urllib.request.Request(
        f"http://{CDP_HOST}:{CDP_PORT}/json/new?{encoded}",
        method="PUT"
    )
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read().decode())


def _cdp_close_tab(tab_id):
    """Close a tab via CDP HTTP API."""
    try:
        req = urllib.request.Request(
            f"http://{CDP_HOST}:{CDP_PORT}/json/close/{tab_id}",
            method="PUT"
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def _cdp_evaluate(ws, expression, cmd_id=1):
    """Evaluate a JS expression via CDP WebSocket. Returns the result value."""
    cmd = json.dumps({
        "id": cmd_id,
        "method": "Runtime.evaluate",
        "params": {
            "expression": expression,
            "returnByValue": True
        }
    })
    ws.send(cmd)
    # Read responses until we get our command's response
    for _ in range(20):  # max 20 messages to find our response
        raw = ws.recv()
        parsed = json.loads(raw)
        if parsed.get("id") == cmd_id:
            result = parsed.get("result", {}).get("result", {})
            return result.get("value")
    return None


# ---------------------------------------------------------------------------
# Content extraction strategies
# ---------------------------------------------------------------------------

def _extract_x_twitter(ws):
    """Extract tweet content from an X/Twitter page via CDP."""
    # Get all article elements' inner text (main post + replies)
    articles_js = """
    (() => {
        const articles = document.querySelectorAll('article');
        const results = [];
        for (const a of articles) {
            results.push(a.innerText);
        }
        return JSON.stringify(results);
    })()
    """
    raw = _cdp_evaluate(ws, articles_js, cmd_id=10)
    if not raw:
        return None, "No articles found on page"

    try:
        articles = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None, f"Failed to parse articles JSON"

    if not articles:
        return None, "No article elements found"

    # Get page title for metadata
    title = _cdp_evaluate(ws, "document.title", cmd_id=11) or ""

    # Parse the first article as the main post
    main_post = articles[0] if articles else ""
    replies = articles[1:] if len(articles) > 1 else []

    # Extract author from title: "(N) Author Name on X: ..."
    author_match = re.search(r'(?:\(\d+\)\s+)?(.+?)\s+on X:', title)
    author = author_match.group(1) if author_match else "Unknown"

    # Build structured content
    content_parts = []
    content_parts.append(f"## Main Post\n\n{main_post}")

    if replies:
        content_parts.append("\n\n## Replies\n")
        for i, reply in enumerate(replies, 1):
            content_parts.append(f"\n### Reply {i}\n\n{reply}")

    return {
        "title": title.split(" on X:")[0].lstrip("(0123456789) ") if " on X:" in title else title,
        "author": author,
        "content": "\n".join(content_parts),
        "article_count": len(articles),
    }, None


def _extract_generic_browser(ws):
    """Extract content from a generic JS-rendered page via CDP."""
    # Try common content selectors
    content_js = """
    (() => {
        const selectors = ['article', 'main', '[role="main"]', '.content', '#content', 'body'];
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (el && el.innerText.trim().length > 100) {
                return JSON.stringify({
                    selector: sel,
                    text: el.innerText,
                    title: document.title
                });
            }
        }
        return JSON.stringify({
            selector: 'body',
            text: document.body?.innerText || '',
            title: document.title
        });
    })()
    """
    raw = _cdp_evaluate(ws, content_js, cmd_id=20)
    if not raw:
        return None, "Failed to evaluate content extraction"

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None, "Failed to parse extracted content"

    return {
        "title": data.get("title", ""),
        "author": "",
        "content": data.get("text", ""),
        "selector": data.get("selector", ""),
    }, None


def _extract_static_html(raw_path, manifest):
    """Extract content from static HTML (no browser needed)."""
    try:
        with open(raw_path, "r", encoding="utf-8", errors="replace") as f:
            html = f.read()
    except Exception as e:
        return None, f"Failed to read HTML: {e}"

    # Extract title from <title> tag
    title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else ""

    # Extract meta description
    desc_match = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
    description = desc_match.group(1) if desc_match else ""

    # Extract og:title and og:description
    og_title_match = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)
    og_desc_match = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']*)["\']', html, re.IGNORECASE)

    # Simple text extraction: strip tags
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()

    if len(text) < 50 and not description:
        return None, "Static HTML extraction produced no meaningful content"

    content_parts = []
    if og_title_match:
        content_parts.append(f"**Title:** {og_title_match.group(1)}")
    if description:
        content_parts.append(f"**Description:** {description}")
    if og_desc_match and og_desc_match.group(1) != description:
        content_parts.append(f"**OG Description:** {og_desc_match.group(1)}")
    if text and len(text) > 50:
        # Truncate to first 5000 chars for preview
        preview = text[:5000]
        if len(text) > 5000:
            preview += "... (truncated)"
        content_parts.append(f"\n## Content\n\n{preview}")

    return {
        "title": (og_title_match.group(1) if og_title_match else title) or manifest.get("title", ""),
        "author": "",
        "content": "\n\n".join(content_parts),
    }, None


# ---------------------------------------------------------------------------
# YAML frontmatter helper
# ---------------------------------------------------------------------------

def _yaml_scalar(value):
    if value is None:
        return "null"
    s = str(value)
    if any(c in s for c in (':', '#', '{', '}', '[', ']', ',', '&', '*',
                             '?', '|', '-', '<', '>', '=', '!', '%',
                             '@', '`', '"', "'")):
        return f'"{s.replace(chr(34), chr(92)+chr(34))}"'
    if s in ('', 'true', 'false', 'null', 'yes', 'no'):
        return f'"{s}"'
    return s


# ---------------------------------------------------------------------------
# Main extract function (adapter contract)
# ---------------------------------------------------------------------------

def extract(raw_path, manifest, output_dir):
    """
    Extract content from a URL source.

    Strategy:
    1. Check if the URL's domain requires browser rendering
    2. If yes and CDP is available: open new tab, render, extract, close
    3. If yes but no CDP: return pending_tooling
    4. If no: parse the static HTML from raw_path

    Args:
        raw_path:   absolute path to the raw downloaded file
        manifest:   the full manifest dict
        output_dir: directory for extraction notes

    Returns:
        {"status": "extracted"|"pending_tooling"|"failed", "notes": [...], "error": ...}
    """
    original_source = manifest.get("original_source", "")
    ingest_id = manifest.get("ingest_id", "unknown")

    # Determine if browser rendering is needed
    import urllib.parse
    parsed_url = urllib.parse.urlparse(original_source)
    netloc = parsed_url.netloc.lower()
    # Strip port if present, then check exact domain match (with and without www.)
    domain = netloc.split(":")[0]
    domain_no_www = domain.lstrip("www.") if domain.startswith("www.") else domain
    needs_browser = domain in BROWSER_REQUIRED_DOMAINS or domain_no_www in BROWSER_REQUIRED_DOMAINS

    extracted_data = None
    error = None

    if needs_browser:
        if not _cdp_available():
            return {
                "status": "pending_tooling",
                "notes": [],
                "error": f"Browser rendering required for {domain} but Chrome CDP not available on {CDP_HOST}:{CDP_PORT}",
            }

        # Open new tab, wait for render, extract, close
        tab_info = None
        ws = None
        try:
            tab_info = _cdp_new_tab(original_source)
            tab_id = tab_info["id"]
            ws_path = f"/devtools/page/{tab_id}"

            # Wait for page to render
            time.sleep(8)

            # Connect via WebSocket
            ws = _WebSocket(CDP_HOST, CDP_PORT, ws_path)

            # Wait a bit more for dynamic content
            time.sleep(3)

            # Route to domain-specific extractor
            if "x.com" in parsed_url.netloc or "twitter.com" in parsed_url.netloc:
                extracted_data, error = _extract_x_twitter(ws)
            else:
                extracted_data, error = _extract_generic_browser(ws)

        except Exception as e:
            error = f"CDP extraction failed: {e}"
        finally:
            if ws:
                ws.close()
            if tab_info:
                _cdp_close_tab(tab_info["id"])
    else:
        # Static HTML extraction
        extracted_data, error = _extract_static_html(raw_path, manifest)

    if extracted_data is None:
        if needs_browser and not _cdp_available():
            # CDP went away mid-extraction — genuinely missing tooling
            return {"status": "pending_tooling", "notes": [], "error": error}
        # CDP was available (or not needed) but extraction still failed — real failure
        return {"status": "failed", "notes": [], "error": error or "No content extracted"}

    # Write extraction note
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    note_filename = f"{ingest_id}_extraction.md"
    note_path = os.path.join(output_dir, note_filename)
    os.makedirs(output_dir, exist_ok=True)

    title = extracted_data.get("title", manifest.get("title", ""))
    author = extracted_data.get("author", "")
    content = extracted_data.get("content", "")
    raw_scope_path = manifest.get("raw_scope_path", "")

    extraction_method = "chrome-cdp-websocket" if needs_browser else "static-html-parse"

    frontmatter_lines = [
        "---",
        f"title: {_yaml_scalar(title)}",
        f"date: {date_str}",
        f"source_type: extraction_note",
        f"raw_scope_path: {_yaml_scalar(raw_scope_path)}",
        f"original_source: {_yaml_scalar(original_source)}",
        f"ingest_id: {_yaml_scalar(ingest_id)}",
        f"content_tier: draft",
        f"extraction_method: {extraction_method}",
    ]
    if author:
        frontmatter_lines.append(f"author: {_yaml_scalar(author)}")
    frontmatter_lines.append("---")

    body = f"\n{content}\n\n## Provenance\n\n"
    body += f"- **raw_scope_path:** `{raw_scope_path}`\n"
    body += f"- **original_source:** `{original_source}`\n"

    try:
        with open(note_path, "w", encoding="utf-8") as f:
            f.write("\n".join(frontmatter_lines))
            f.write("\n")
            f.write(body)
    except Exception as e:
        return {"status": "failed", "notes": [], "error": f"Failed to write note: {e}"}

    return {
        "status": "extracted",
        "notes": [note_path],
        "error": None,
    }
