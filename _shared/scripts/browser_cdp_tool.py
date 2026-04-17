#!/usr/bin/env python3
"""
browser_cdp_tool.py — Robinhood CDP helper.
Zero external Python dependencies.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from typing import Any


CDP_LIST_URL = "http://127.0.0.1:9222/json/list"
ROBINHOOD_TITLE = "Investing | Robinhood"
ROBINHOOD_URL_PREFIX = "https://robinhood.com/"
CHARTLI_PATH = shutil.which("chartli")
DEFAULT_DEEP_HOLDINGS = 5


def fail(code: int, msg: str) -> None:
    print(f"ERR | {code} | {msg}", file=sys.stderr)
    raise SystemExit(code)


def http_json(url: str, headers: dict[str, str] | None = None) -> Any:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        fail(exc.code, f"HTTP {exc.code} for {url}: {body[:300]}")
    except urllib.error.URLError as exc:
        fail(2, f"Request failed for {url}: {exc}")


def list_tabs() -> list[dict[str, Any]]:
    data = http_json(CDP_LIST_URL)
    if not isinstance(data, list):
        fail(2, "Unexpected CDP tab list response")
    return data


def find_robinhood_tab() -> dict[str, Any]:
    fallback: dict[str, Any] | None = None
    for tab in list_tabs():
        if tab.get("type") != "page":
            continue
        url = str(tab.get("url", ""))
        if not url.startswith(ROBINHOOD_URL_PREFIX):
            continue
        if tab.get("title") == ROBINHOOD_TITLE:
            return tab
        if fallback is None:
            fallback = tab
    if fallback is not None:
        return fallback
    fail(3, "Robinhood tab not found in CDP target list")


class DevToolsWebSocket:
    def __init__(self, ws_url: str):
        parsed = urllib.parse.urlparse(ws_url)
        if parsed.scheme not in {"ws", "wss"}:
            fail(2, f"Unsupported websocket scheme: {parsed.scheme}")
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        self.path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
        self.secure = parsed.scheme == "wss"
        self.sock: socket.socket | ssl.SSLSocket | None = None

    def __enter__(self) -> "DevToolsWebSocket":
        raw = socket.create_connection((self.host, self.port), timeout=30)
        if self.secure:
            context = ssl.create_default_context()
            self.sock = context.wrap_socket(raw, server_hostname=self.host)
        else:
            self.sock = raw
        self._handshake()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _handshake(self) -> None:
        assert self.sock is not None
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = self._read_http_headers()
        expected = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
            ).digest()
        ).decode("ascii")
        if (
            "101" not in response.splitlines()[0]
            or f"sec-websocket-accept: {expected}".lower() not in response.lower()
        ):
            fail(2, f"WebSocket handshake failed: {response.splitlines()[0]}")

    def _read_http_headers(self) -> str:
        assert self.sock is not None
        chunks = bytearray()
        while b"\r\n\r\n" not in chunks:
            part = self.sock.recv(4096)
            if not part:
                fail(2, "Unexpected EOF during websocket handshake")
            chunks.extend(part)
        header_bytes = bytes(chunks.split(b"\r\n\r\n", 1)[0])
        return header_bytes.decode("utf-8", errors="replace")

    def send_json(self, payload: dict[str, Any]) -> None:
        self._send_frame(json.dumps(payload).encode("utf-8"), opcode=0x1)

    def recv_json(self) -> dict[str, Any]:
        while True:
            opcode, payload = self._read_frame()
            if opcode == 0x1:
                return json.loads(payload.decode("utf-8"))
            if opcode == 0x8:
                fail(2, "DevTools websocket closed unexpectedly")

    def _send_frame(self, payload: bytes, opcode: int) -> None:
        assert self.sock is not None
        mask = secrets.token_bytes(4)
        header = bytearray([0x80 | (opcode & 0x0F)])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(length.to_bytes(2, "big"))
        else:
            header.append(0x80 | 127)
            header.extend(length.to_bytes(8, "big"))
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _read_exact(self, size: int) -> bytes:
        assert self.sock is not None
        chunks = bytearray()
        while len(chunks) < size:
            part = self.sock.recv(size - len(chunks))
            if not part:
                fail(2, "Unexpected EOF reading websocket frame")
            chunks.extend(part)
        return bytes(chunks)

    def _read_frame(self) -> tuple[int, bytes]:
        first, second = self._read_exact(2)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = int.from_bytes(self._read_exact(2), "big")
        elif length == 127:
            length = int.from_bytes(self._read_exact(8), "big")
        mask = self._read_exact(4) if masked else b""
        payload = self._read_exact(length)
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload


def runtime_evaluate(ws_url: str, expression: str, await_promise: bool = False) -> Any:
    payload = {
        "id": 1,
        "method": "Runtime.evaluate",
        "params": {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": await_promise,
        },
    }
    with DevToolsWebSocket(ws_url) as ws:
        ws.send_json(payload)
        response = ws.recv_json()
    if "exceptionDetails" in response.get("result", {}):
        details = response["result"]["exceptionDetails"]
        exception = details.get("exception") or {}
        description = exception.get("description") or details.get(
            "text", "unknown error"
        )
        fail(4, f"Runtime.evaluate failed: {description}")
    return response.get("result", {}).get("result", {}).get("value")


def js_string(value: str) -> str:
    return json.dumps(value)


def get_robinhood_auth_state(ws_url: str) -> dict[str, Any]:
    value = runtime_evaluate(
        ws_url,
        "localStorage.getItem('web:auth_state')",
    )
    if not value:
        fail(4, "Robinhood auth state not found in localStorage")
    try:
        auth_state = json.loads(value)
    except json.JSONDecodeError:
        fail(4, "Failed to parse Robinhood auth state JSON")
    if not isinstance(auth_state, dict):
        fail(4, "Robinhood auth state is not an object")
    return auth_state


def get_bearer_token(auth_state: dict[str, Any]) -> str:
    token = auth_state.get("read_only_secondary_access_token") or auth_state.get(
        "access_token"
    )
    if not token or not isinstance(token, str):
        fail(4, "No usable Robinhood bearer token found in auth state")
    return token


def robinhood_get_json(url: str, token: str) -> Any:
    return http_json(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "browser_cdp_tool",
        },
    )


def decimal_str(value: str | float | int) -> Decimal:
    return Decimal(str(value))


def format_money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def format_price(value: Decimal) -> str:
    if value >= Decimal("1"):
        quantum = Decimal("0.01")
    elif value >= Decimal("0.01"):
        quantum = Decimal("0.0001")
    else:
        quantum = Decimal("0.00000001")
    return str(value.quantize(quantum, rounding=ROUND_HALF_UP))


def format_quantity(value: Decimal) -> str:
    normalized = format(value.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def fetch_equity_quotes(
    instrument_ids: list[str], token: str
) -> dict[str, dict[str, Any]]:
    quotes: dict[str, dict[str, Any]] = {}
    for group in chunked(instrument_ids, 75):
        url = (
            "https://api.robinhood.com/marketdata/quotes/?bounds=24_5&ids="
            + urllib.parse.quote(",".join(group), safe=",")
            + "&include_bbo_source=true&include_inactive=false"
        )
        data = robinhood_get_json(url, token)
        for row in data.get("results", []):
            instrument_id = row.get("instrument_id")
            if instrument_id:
                quotes[instrument_id] = row
    return quotes


def fetch_crypto_quotes(
    currency_pair_ids: list[str], token: str
) -> dict[str, dict[str, Any]]:
    quotes: dict[str, dict[str, Any]] = {}
    for group in chunked(currency_pair_ids, 75):
        url = (
            "https://api.robinhood.com/marketdata/forex/quotes/?ids="
            + urllib.parse.quote(",".join(group), safe=",")
        )
        data = robinhood_get_json(url, token)
        for row in data.get("results", []):
            row_id = row.get("id")
            if row_id:
                quotes[row_id] = row
    return quotes


def fetch_equity_historicals(
    instrument_ids: list[str], token: str
) -> dict[str, list[Decimal]]:
    history_map: dict[str, list[Decimal]] = {}
    for group in chunked(instrument_ids, 20):
        url = (
            "https://api.robinhood.com/marketdata/historicals/?bounds=24_5&ids="
            + urllib.parse.quote(",".join(group), safe=",")
            + "&interval=5minute&span=day"
        )
        data = robinhood_get_json(url, token)
        for row in data.get("results", []):
            instrument_url = str(row.get("instrument", "")).rstrip("/")
            instrument_id = (
                instrument_url.split("/")[-1]
                if instrument_url
                else row.get("InstrumentID")
            )
            if not instrument_id:
                continue
            points = row.get("historicals", [])
            closes = [
                decimal_str(point.get("close_price"))
                for point in points
                if point.get("close_price") is not None
            ]
            if closes:
                history_map[instrument_id] = closes
    return history_map


def fetch_crypto_historicals(
    currency_pair_ids: list[str], token: str
) -> dict[str, list[Decimal]]:
    history_map: dict[str, list[Decimal]] = {}
    for group in chunked(currency_pair_ids, 20):
        url = (
            "https://api.robinhood.com/marketdata/forex/historicals/?bounds=24_7&ids="
            + urllib.parse.quote(",".join(group), safe=",")
            + "&interval=5minute&span=day"
        )
        data = robinhood_get_json(url, token)
        for row in data.get("results", []):
            row_id = row.get("id")
            if not row_id:
                continue
            points = row.get("data_points", [])
            closes = [
                decimal_str(point.get("close_price"))
                for point in points
                if point.get("close_price") is not None
            ]
            if closes:
                history_map[row_id] = closes
    return history_map


def downsample_series(values: list[Decimal], target_points: int = 32) -> list[Decimal]:
    if len(values) <= target_points:
        return values
    sampled: list[Decimal] = []
    last_index = len(values) - 1
    for idx in range(target_points):
        source_index = round(idx * last_index / (target_points - 1))
        sampled.append(values[source_index])
    return sampled


def build_sparkline_payload(
    values: list[Decimal], width: int = 16, source_points: int = 32
) -> dict[str, Any] | None:
    sampled = downsample_series(values, target_points=source_points)
    rendered = render_connector_spark(values, width=width)
    if not rendered:
        return None
    return {
        "rendered": rendered,
        "width": width,
        "source_points": len(sampled),
        "points": [format_price(value) for value in sampled],
    }


def render_connector_spark(
    values: list[Decimal], width: int = 16, height: int = 4
) -> str | None:
    sampled = downsample_series(values, target_points=width * 2)
    if len(sampled) < 2:
        return None
    low = min(sampled)
    high = max(sampled)
    if high == low:
        return "⠒" * width

    left_bits = [0x01, 0x02, 0x04, 0x40]
    right_bits = [0x08, 0x10, 0x20, 0x80]
    span = high - low
    levels: list[int] = []
    for value in sampled:
        normalized = (value - low) / span
        level = int((height - 1) - (normalized * (height - 1)))
        levels.append(max(0, min(height - 1, level)))

    chars: list[str] = []
    for idx in range(0, len(levels), 2):
        left_level = levels[idx]
        right_level = levels[min(idx + 1, len(levels) - 1)]
        bits = left_bits[left_level] | right_bits[right_level]

        low_level = min(left_level, right_level)
        high_level = max(left_level, right_level)
        if high_level - low_level > 1:
            for fill_level in range(low_level + 1, high_level):
                bits |= (
                    left_bits[fill_level]
                    if left_level < right_level
                    else right_bits[fill_level]
                )

        chars.append(chr(0x2800 + bits))
    return "".join(chars)


def render_chartli_spark(values: list[Decimal]) -> str | None:
    if not CHARTLI_PATH or len(values) < 2:
        return None
    payload_values = downsample_series(values)
    payload = "\n".join(format(value, "f") for value in payload_values) + "\n"
    try:
        result = subprocess.run(
            [CHARTLI_PATH, "-t", "spark"],
            input=payload,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("S1 "):
            return stripped[3:]
    return None


def render_portfolio_report(portfolio: dict[str, Any]) -> str:
    holdings = portfolio.get("holdings", [])
    spark_present = any(item.get("sparkline_1d") for item in holdings)
    symbol_width = max([6] + [len(str(item.get("symbol", ""))) for item in holdings])
    type_width = max([6] + [len(str(item.get("type", ""))) for item in holdings])
    quantity_width = max(
        [8] + [len(str(item.get("quantity", ""))) for item in holdings]
    )
    price_width = max([9] + [len(str(item.get("price_usd", ""))) for item in holdings])
    value_width = max(
        [9] + [len(str(item.get("market_value_usd", ""))) for item in holdings]
    )

    lines = [
        f"Robinhood holdings  total ${portfolio.get('total_market_value_usd')}  count {portfolio.get('count')}  retrieved {portfolio.get('retrieved_at_utc')}",
        "",
    ]
    header = f"{'Symbol':<{symbol_width}}  {'Type':<{type_width}}  {'Quantity':>{quantity_width}}  {'Price USD':>{price_width}}  {'Value USD':>{value_width}}"
    if spark_present:
        header += "  Trend"
    lines.append(header)
    for item in holdings:
        row = (
            f"{str(item.get('symbol', '')):<{symbol_width}}  "
            f"{str(item.get('type', '')):<{type_width}}  "
            f"{str(item.get('quantity', '')):>{quantity_width}}  "
            f"{str(item.get('price_usd', '')):>{price_width}}  "
            f"{str(item.get('market_value_usd', '')):>{value_width}}"
        )
        if spark_present:
            row += f"  {item.get('sparkline_1d') or ''}"
        lines.append(row.rstrip())
    return "\n".join(lines)


def load_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def lines_between(text: str, start: str, end_markers: list[str]) -> list[str]:
    start_index = text.find(start)
    if start_index < 0:
        return []
    slice_start = start_index + len(start)
    slice_end = len(text)
    for marker in end_markers:
        marker_index = text.find(marker, slice_start)
        if marker_index >= 0:
            slice_end = min(slice_end, marker_index)
    section = text[slice_start:slice_end].strip()
    return [line.strip() for line in section.splitlines() if line.strip()]


def pairs_from_lines(lines: list[str]) -> dict[str, str]:
    pairs: dict[str, str] = {}
    idx = 0
    while idx + 1 < len(lines):
        key = lines[idx]
        value = lines[idx + 1]
        if key and value and key not in pairs:
            pairs[key] = value
        idx += 2
    return pairs


def wait_for_page_markers(
    ws_url: str, markers: list[str], timeout_seconds: float = 25.0
) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        text = (
            runtime_evaluate(ws_url, "document.body ? document.body.innerText : ''")
            or ""
        )
        if all(marker in text for marker in markers):
            return
        time.sleep(0.5)
    fail(4, f"Timed out waiting for page markers: {', '.join(markers)}")


def navigate_robinhood_detail_page(ws_url: str, url: str, markers: list[str]) -> None:
    runtime_evaluate(
        ws_url,
        f"window.location.href = {js_string(url)}; true",
    )
    wait_for_page_markers(ws_url, markers)


def click_text_control(ws_url: str, label: str) -> bool:
    expression = f"""
(() => {{
  const target = {js_string(label)};
  const nodes = Array.from(document.querySelectorAll('button,[role="tab"],a,div,span'));
  const node = nodes.find((candidate) => candidate && candidate.innerText && candidate.innerText.trim() === target);
  if (!node) return false;
  node.click();
  return true;
}})()
"""
    return bool(runtime_evaluate(ws_url, expression))


def click_exact_link_text(ws_url: str, label: str) -> bool:
    expression = f"""
(() => {{
  const target = {js_string(label)};
  const links = Array.from(document.querySelectorAll('a'));
  const link = links.find((candidate) => (candidate.innerText || '').trim() === target);
  if (!link) return false;
  link.click();
  return true;
}})()
"""
    return bool(runtime_evaluate(ws_url, expression))


def press_escape(ws_url: str) -> None:
    runtime_evaluate(
        ws_url,
        """
(() => {
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  document.dispatchEvent(new KeyboardEvent('keyup', { key: 'Escape', bubbles: true }));
  return true;
})()
""",
    )


def click_first_containing_text(ws_url: str, text: str) -> bool:
    expression = f"""
(() => {{
  const target = {js_string(text)};
  const nodes = Array.from(document.querySelectorAll('button,[role="button"],[role="tab"],a,div,span'));
  const node = nodes.find((candidate) => candidate && candidate.innerText && candidate.innerText.includes(target));
  if (!node) return false;
  node.click();
  return true;
}})()
"""
    return bool(runtime_evaluate(ws_url, expression))


def scroll_detail_page(ws_url: str) -> None:
    runtime_evaluate(
        ws_url,
        """
(async () => {
  window.scrollTo(0, document.body.scrollHeight);
  await new Promise((resolve) => setTimeout(resolve, 1200));
  return true;
})()
""",
        await_promise=True,
    )


def get_page_text(ws_url: str) -> str:
    return str(
        runtime_evaluate(ws_url, "document.body ? document.body.innerText : ''") or ""
    )


def get_crypto_panel_snapshot(ws_url: str, symbol: str, side: str) -> dict[str, Any]:
    expression = f"""
(() => {{
  const symbol = {js_string(symbol.upper())};
  const side = {js_string(side.lower())};
  const sideTitle = `${{side === 'sell' ? 'Sell' : 'Buy'}} ${{symbol}}`;
  const nodes = Array.from(document.querySelectorAll('section,aside,form,div'));
  const scored = nodes.map((node) => {{
    const text = (node.innerText || '').trim();
    const lineCount = text ? text.split(/\\n+/).filter(Boolean).length : 0;
    let score = 0;
    if (text.includes(sideTitle)) score += 5;
    if (text.includes('Review order')) score += 3;
    if (text.includes('Submit buy') || text.includes('Submit sell')) score += 3;
    if (text.includes('Amount')) score += 2;
    if (text.includes('Est BTC price') || text.includes(`Est ${{symbol}} price`)) score += 2;
    if (text.includes('Buy spread') || text.includes('Sell spread')) score += 2;
    if (text.includes('available')) score += 1;
    if (lineCount > 0 && lineCount < 80) score += 2;
    if (text.length > 0 && text.length < 1500) score += 2;
    return {{ node, text, score, lineCount }};
  }}).filter((item) => item.score > 0 && item.text.length > 0)
    .sort((a, b) => b.score - a.score || a.text.length - b.text.length || a.lineCount - b.lineCount);
  const chosen = scored.length ? scored[0].node : null;
  const cleanLines = chosen ? (chosen.innerText || '').split(/\\n+/).map((line) => line.trim()).filter(Boolean) : [];
  const inputs = chosen ? Array.from(chosen.querySelectorAll('input, textarea')).map((el) => ({{
    value: el.value || '',
    placeholder: el.placeholder || '',
    type: el.type || '',
    aria_label: el.getAttribute('aria-label') || ''
  }})) : [];
  const selects = chosen ? Array.from(chosen.querySelectorAll('select')).map((el) => ({{
    value: el.value || '',
    options: Array.from(el.options).map((opt) => opt.textContent || '').filter(Boolean)
  }})) : [];
  const buttons = chosen ? Array.from(chosen.querySelectorAll('button')).map((el) => ({{
    text: (el.innerText || '').trim(),
    disabled: !!el.disabled
  }})).filter((item) => item.text) : [];
  return {{
    symbol,
    side,
    panel_title: sideTitle,
    headline_price_usd: null,
    lines: cleanLines,
    inputs,
    selects,
    buttons,
  }};
}})()
"""
    result = runtime_evaluate(ws_url, expression)
    return result if isinstance(result, dict) else {}


def get_modal_snapshot(ws_url: str) -> dict[str, Any] | None:
    expression = """
(() => {
  const dialog = document.querySelector('[role="dialog"], [aria-modal="true"]');
  if (!dialog) return null;
  const lines = (dialog.innerText || '').split(/\\n+/).map((line) => line.trim()).filter(Boolean);
  return { lines, raw_text: lines.join('\\n') };
})()
"""
    result = runtime_evaluate(ws_url, expression)
    return result if isinstance(result, dict) else None


def extract_order_summary(lines: list[str]) -> dict[str, str]:
    output: dict[str, str] = {}
    asset_codes = {"BTC", "ETH", "DOGE", "SHIB", "SOL", "ADA", "XLM", "TRUMP", "XRP"}
    idx = 0
    while idx < len(lines):
        current = lines[idx]
        if current in {
            "Buy in",
            "Sell in",
            "Amount",
            "Est BTC price",
        } and idx + 1 < len(lines):
            next_line = lines[idx + 1]
            if current == "Amount" and (
                next_line in {"Buy All", "Review order"}
                or next_line.startswith("Buy spread")
                or next_line.startswith("Sell spread")
            ):
                idx += 1
                continue
            output[current] = next_line
            idx += 2
            continue
        if current.startswith("Buy spread") or current.startswith("Sell spread"):
            spread_value = None
            for probe in lines[idx + 1 : idx + 4]:
                if probe.startswith("$"):
                    spread_value = probe
                    break
            output[current] = spread_value or ""
        if current in asset_codes and idx + 1 < len(lines):
            output[current] = lines[idx + 1]
        if current.endswith(" available") or current.endswith(
            " buying power available"
        ):
            output["Available"] = current
        idx += 1
    return output


def parse_price_from_title(title: str) -> str | None:
    if " - $" not in title:
        return None
    try:
        return title.split(" - $", 1)[1].split(" | ", 1)[0]
    except IndexError:
        return None


def build_crypto_detail_url(symbol: str) -> str:
    return f"https://robinhood.com/crypto/{symbol.upper()}"


def ensure_crypto_side(ws_url: str, symbol: str, side: str) -> None:
    desired_label = f"{'Sell' if side.lower() == 'sell' else 'Buy'} {symbol.upper()}"
    field_marker = "Sell in" if side.lower() == "sell" else "Buy in"
    for _ in range(6):
        click_exact_link_text(ws_url, desired_label) or click_text_control(
            ws_url, desired_label
        ) or click_first_containing_text(ws_url, desired_label)
        time.sleep(0.4)
        panel = get_crypto_panel_snapshot(ws_url, symbol, side)
        lines = panel.get("lines", []) if isinstance(panel, dict) else []
        if any(line == field_marker for line in lines):
            return
    fail(4, f"Failed to switch crypto panel to {side} side for {symbol.upper()}")


def fetch_crypto_panel(
    symbol: str,
    side: str = "buy",
    include_spread_modal: bool = True,
) -> dict[str, Any]:
    tab = find_robinhood_tab()
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        fail(3, "Robinhood tab missing webSocketDebuggerUrl")
    original_url = str(tab.get("url") or ROBINHOOD_URL_PREFIX)
    detail_url = build_crypto_detail_url(symbol)
    navigate_robinhood_detail_page(str(ws_url), detail_url, [symbol.upper()])
    time.sleep(1.0)
    ensure_crypto_side(str(ws_url), symbol, side)
    panel = get_crypto_panel_snapshot(str(ws_url), symbol, side)
    panel["field_map"] = extract_order_summary(panel.get("lines", []))
    panel["detail_url"] = detail_url
    panel["page_title"] = runtime_evaluate(str(ws_url), "document.title")
    panel["headline_price_usd"] = parse_price_from_title(
        str(panel.get("page_title") or "")
    )
    if include_spread_modal:
        spread_text = "Sell spread" if side.lower() == "sell" else "Buy spread"
        if click_first_containing_text(str(ws_url), spread_text):
            time.sleep(0.5)
            panel["spread_modal"] = get_modal_snapshot(str(ws_url))
            press_escape(str(ws_url))
            time.sleep(0.2)
        else:
            panel["spread_modal"] = None
    navigate_robinhood_detail_page(
        str(ws_url), original_url, markers_for_url(original_url)
    )
    return {
        "success": True,
        "retrieved_at_utc": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "tab_id": tab.get("id"),
        "source": {
            "cdp_list_url": CDP_LIST_URL,
            "tab_websocket_url": ws_url,
        },
        "crypto_order_panel": panel,
    }


def extract_detail_sections_from_text(text: str) -> dict[str, Any]:
    about_lines = lines_between(
        text, "About", ["Key statistics", "News", "Trading Trends"]
    )
    key_statistics_lines = lines_between(
        text, "Key statistics", ["Related lists", "News", "Trading Trends"]
    )
    related_lists_lines = lines_between(
        text, "Related lists", ["News", "Trading Trends", "Analyst ratings"]
    )
    history_lines = lines_between(
        text, "History", ["People also own", "News", "Disclosures"]
    )
    people_also_own_lines = lines_between(
        text, "People also own", ["Disclosures", "You may also like", "Show more"]
    )

    description_lines: list[str] = []
    about_fact_lines: list[str] = []
    for line in about_lines:
        if about_fact_lines or line in {"CEO", "Employees", "Headquarters", "Founded"}:
            about_fact_lines.append(line)
        else:
            description_lines.append(line)

    return {
        "about": {
            "description": " ".join(description_lines).replace(" Show more", "").strip()
            or None,
            "facts": pairs_from_lines(about_fact_lines),
            "raw_lines": about_lines,
        },
        "key_statistics": pairs_from_lines(key_statistics_lines),
        "related_lists": [line for line in related_lists_lines if line != "Show more"],
        "history": history_lines,
        "people_also_own": [
            line for line in people_also_own_lines if line != "Show more"
        ],
    }


def capture_trading_trends(ws_url: str) -> dict[str, Any]:
    tab_names = ["Robinhood", "Hedge funds", "Insiders"]
    trends: dict[str, Any] = {}
    for tab_name in tab_names:
        click_text_control(ws_url, tab_name)
        time.sleep(0.8)
        text = get_page_text(ws_url)
        lines = lines_between(
            text,
            "Trading Trends",
            ["Analyst ratings", "Short interest", "Research report", "History"],
        )
        filtered = [line for line in lines if line not in tab_names]
        trends[tab_name.lower().replace(" ", "_")] = {
            "tab": tab_name,
            "lines": filtered,
            "raw_text": "\n".join(filtered),
        }
    return trends


def build_detail_url(holding: dict[str, Any]) -> str:
    symbol = str(holding.get("symbol", "")).upper()
    if holding.get("type") == "crypto":
        return f"https://robinhood.com/crypto/{symbol}"
    return f"https://robinhood.com/stocks/{symbol}"


def markers_for_url(url: str) -> list[str]:
    if "/stocks/" in url or "/crypto/" in url:
        symbol = url.rstrip("/").split("/")[-1].split("?")[0].upper()
        return [symbol]
    return ["Robinhood"]


def fetch_holding_detail(
    ws_url: str, holding: dict[str, Any], delay_seconds: float
) -> dict[str, Any]:
    detail_url = build_detail_url(holding)
    symbol = str(holding.get("symbol", ""))
    markers = [symbol]
    if holding.get("type") == "stock":
        markers.append("About")
    navigate_robinhood_detail_page(ws_url, detail_url, markers)
    scroll_detail_page(ws_url)
    text = get_page_text(ws_url)
    sections = extract_detail_sections_from_text(text)
    sections["detail_url"] = detail_url
    sections["page_title"] = runtime_evaluate(ws_url, "document.title")
    sections["trading_trends"] = capture_trading_trends(ws_url)
    time.sleep(delay_seconds)
    return sections


def build_portfolio(
    mode: str = "shallow",
    detail_delay_seconds: float = 1.5,
    max_deep_holdings: int = DEFAULT_DEEP_HOLDINGS,
) -> dict[str, Any]:
    tab = find_robinhood_tab()
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        fail(3, "Robinhood tab missing webSocketDebuggerUrl")

    auth_state = get_robinhood_auth_state(str(ws_url))
    token = get_bearer_token(auth_state)

    account_number = runtime_evaluate(
        str(ws_url),
        "localStorage.getItem('web-app:selected-account-number') || ''",
    )
    if not account_number:
        fail(4, "Could not determine selected Robinhood account number")

    equity_positions = robinhood_get_json(
        f"https://api.robinhood.com/positions/?account_number={account_number}&nonzero=true",
        token,
    ).get("results", [])
    crypto_holdings = robinhood_get_json(
        "https://nummus.robinhood.com/holdings/",
        token,
    ).get("results", [])

    instrument_ids = sorted(
        {row["instrument_id"] for row in equity_positions if row.get("instrument_id")}
    )
    equity_quotes = fetch_equity_quotes(instrument_ids, token)
    equity_historicals = fetch_equity_historicals(instrument_ids, token)

    currency_pair_ids = sorted(
        {
            row["currency_pair_id"]
            for row in crypto_holdings
            if row.get("currency_pair_id") and decimal_str(row.get("quantity", "0")) > 0
        }
    )
    crypto_quotes = fetch_crypto_quotes(currency_pair_ids, token)
    crypto_historicals = fetch_crypto_historicals(currency_pair_ids, token)

    holdings: list[dict[str, Any]] = []
    total_market_value = Decimal("0")

    for row in equity_positions:
        quantity = decimal_str(row.get("quantity", "0"))
        quote = equity_quotes.get(row.get("instrument_id", ""), {})
        sparkline_payload = build_sparkline_payload(
            equity_historicals.get(row.get("instrument_id", ""), [])
        )
        price = decimal_str(
            quote.get("last_extended_hours_trade_price")
            or quote.get("last_trade_price")
            or quote.get("previous_close")
            or "0"
        )
        market_value = quantity * price
        total_market_value += market_value
        holdings.append(
            {
                "type": "stock",
                "symbol": row.get("symbol"),
                "instrument_id": row.get("instrument_id"),
                "quantity": format_quantity(quantity),
                "price_usd": format_price(price),
                "market_value_usd": format_money(market_value),
                "sparkline_1d": sparkline_payload["rendered"]
                if sparkline_payload
                else None,
                "sparkline_1d_data": sparkline_payload,
            }
        )

    for row in crypto_holdings:
        quantity = decimal_str(row.get("quantity", "0"))
        if quantity <= 0:
            continue
        quote = crypto_quotes.get(row.get("currency_pair_id", ""), {})
        sparkline_payload = build_sparkline_payload(
            crypto_historicals.get(row.get("currency_pair_id", ""), [])
        )
        price = decimal_str(
            quote.get("mark_price")
            or quote.get("ask_price")
            or quote.get("bid_price")
            or "0"
        )
        market_value = quantity * price
        total_market_value += market_value
        currency = row.get("currency") or {}
        holdings.append(
            {
                "type": "crypto",
                "symbol": currency.get("code"),
                "currency_pair_id": row.get("currency_pair_id"),
                "quantity": format_quantity(quantity),
                "price_usd": format_price(price),
                "market_value_usd": format_money(market_value),
                "sparkline_1d": sparkline_payload["rendered"]
                if sparkline_payload
                else None,
                "sparkline_1d_data": sparkline_payload,
            }
        )

    holdings.sort(key=lambda item: Decimal(item["market_value_usd"]), reverse=True)
    original_url = str(tab.get("url") or ROBINHOOD_URL_PREFIX)
    if mode == "deep":
        deep_holdings = (
            holdings if max_deep_holdings <= 0 else holdings[:max_deep_holdings]
        )
        for holding in deep_holdings:
            holding["detail_page"] = fetch_holding_detail(
                str(ws_url), holding, detail_delay_seconds
            )
        navigate_robinhood_detail_page(
            str(ws_url), original_url, markers_for_url(original_url)
        )
    return {
        "success": True,
        "mode": mode,
        "retrieved_at_utc": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "source": {
            "cdp_list_url": CDP_LIST_URL,
            "tab_websocket_url": ws_url,
        },
        "tab_id": tab.get("id"),
        "title": tab.get("title"),
        "account_number": account_number,
        "count": len(holdings),
        "total_market_value_usd": format_money(total_market_value),
        "holdings": holdings,
    }


def cmd_tabs() -> None:
    print(json.dumps(list_tabs(), indent=2))


def cmd_eval(code: str) -> None:
    tab = find_robinhood_tab()
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        fail(3, "Robinhood tab missing webSocketDebuggerUrl")
    print(
        json.dumps(runtime_evaluate(str(ws_url), code, await_promise=False), indent=2)
    )


def cmd_portfolio(
    mode: str, detail_delay_seconds: float, max_deep_holdings: int
) -> None:
    print(
        json.dumps(
            build_portfolio(
                mode=mode,
                detail_delay_seconds=detail_delay_seconds,
                max_deep_holdings=max_deep_holdings,
            ),
            indent=2,
        )
    )


def cmd_report(input_path: str) -> None:
    payload = load_json_file(input_path)
    print(render_portfolio_report(payload))


def cmd_crypto_panel(symbol: str, side: str, include_spread_modal: bool) -> None:
    print(
        json.dumps(
            fetch_crypto_panel(
                symbol=symbol,
                side=side,
                include_spread_modal=include_spread_modal,
            ),
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="browser_cdp_tool - Robinhood CDP tool"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("tabs", help="List CDP tabs").set_defaults(
        func=lambda _: cmd_tabs()
    )
    portfolio_parser = subparsers.add_parser(
        "portfolio", help="Read Robinhood holdings"
    )
    portfolio_parser.add_argument(
        "--mode", choices=["shallow", "deep"], default="shallow"
    )
    portfolio_parser.add_argument("--deep", action="store_true")
    portfolio_parser.add_argument("--deep-full", action="store_true")
    portfolio_parser.add_argument("--detail-delay-seconds", type=float, default=1.5)
    portfolio_parser.add_argument(
        "--max-deep-holdings", type=int, default=DEFAULT_DEEP_HOLDINGS
    )
    portfolio_parser.set_defaults(
        func=lambda args: cmd_portfolio(
            mode="deep" if args.deep else args.mode,
            detail_delay_seconds=args.detail_delay_seconds,
            max_deep_holdings=0 if args.deep_full else args.max_deep_holdings,
        )
    )

    report_parser = subparsers.add_parser(
        "report", help="Render gridless holdings report from JSON"
    )
    report_parser.add_argument("--input", required=True)
    report_parser.set_defaults(func=lambda args: cmd_report(args.input))

    crypto_panel_parser = subparsers.add_parser(
        "crypto-panel", help="Read-only Robinhood crypto order panel state"
    )
    crypto_panel_parser.add_argument("--symbol", required=True)
    crypto_panel_parser.add_argument("--side", choices=["buy", "sell"], default="buy")
    crypto_panel_parser.add_argument("--no-spread-modal", action="store_true")
    crypto_panel_parser.set_defaults(
        func=lambda args: cmd_crypto_panel(
            symbol=args.symbol,
            side=args.side,
            include_spread_modal=not args.no_spread_modal,
        )
    )

    eval_parser = subparsers.add_parser("eval", help="Evaluate JS in Robinhood tab")
    eval_parser.add_argument("code")
    eval_parser.set_defaults(func=lambda args: cmd_eval(args.code))

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
