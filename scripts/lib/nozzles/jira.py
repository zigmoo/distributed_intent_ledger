"""Jira wiki markup formatter."""

import re
from typing import List

from nozzles.base import BaseFormatter


# Panel style → border color / background color
_PANEL_STYLES = {
    "info":    {"borderColor": "#4a6785", "bgColor": "#deebff"},
    "warning": {"borderColor": "#c9a825", "bgColor": "#fffae6"},
    "error":   {"borderColor": "#cc3333", "bgColor": "#ffebe6"},
    "success": {"borderColor": "#36802d", "bgColor": "#e3fcef"},
}


class JiraFormatter(BaseFormatter):
    """Render content as Jira wiki markup."""

    # ── Block elements ────────────────────────────────────────────

    def title(self, text: str) -> str:
        return f"h1. {text}"

    def header(self, text: str) -> str:
        return f"h3. {text}"

    def subheader(self, text: str) -> str:
        return f"h4. {text}"

    def bullet(self, text: str) -> str:
        return f"* {text}"

    def numbered(self, n: int, text: str) -> str:
        # Jira uses `# text` for every item (auto-numbered), not `1. text`.
        return f"# {text}"

    def milestone(self, text: str) -> str:
        return f"* (/) {text}"

    def meta(self, text: str) -> str:
        return f"_{text}_"

    def separator(self) -> str:
        return "----"

    def spacer(self) -> str:
        return ""

    # ── Inline elements ──────────────────────────────────────────

    def bold(self, text: str) -> str:
        return f"*{text}*"

    def italic(self, text: str) -> str:
        return f"_{text}_"

    def code(self, text: str) -> str:
        return "{{" + text + "}}"

    def link(self, text: str, url: str) -> str:
        return f"[{text}|{url}]"

    # ── Composite blocks ─────────────────────────────────────────

    def code_block(self, text: str, language: str = "") -> str:
        if language:
            return f"{{code:{language}}}\n{text}\n{{code}}"
        return f"{{noformat}}\n{text}\n{{noformat}}"

    def table(self, headers: List[str], rows: List[List[str]]) -> str:
        escaped_headers = [self._escape_cell(h) for h in headers]
        header_line = "||" + "||".join(escaped_headers) + "||"

        lines = [header_line]
        for row in rows:
            escaped_cells = [self._escape_cell(c) for c in row]
            lines.append("|" + "|".join(escaped_cells) + "|")
        return "\n".join(lines)

    def panel(self, text: str, title: str = "", style: str = "info") -> str:
        colors = _PANEL_STYLES.get(style, _PANEL_STYLES["info"])
        parts = [
            f"title={title}" if title else None,
            "borderStyle=solid",
            f"borderColor={colors['borderColor']}",
            f"bgColor={colors['bgColor']}",
        ]
        params = "|".join(p for p in parts if p)
        return f"{{panel:{params}}}\n{text}\n{{panel}}"

    # ── Escaping ─────────────────────────────────────────────────

    def escape(self, text: str) -> str:
        """Escape pipes and curly braces that would break Jira markup."""
        text = text.replace("{", "\\{").replace("}", "\\}")
        text = text.replace("|", "\\|")
        return text

    def _escape_cell(self, text: str) -> str:
        """Escape pipe characters inside table cells."""
        return str(text).replace("|", "\\|")

    # ── Wrap / join ──────────────────────────────────────────────

    def wrap(self, body: str, title: str = "") -> str:
        """No wrapper needed for Jira wiki markup."""
        return body


# Module-level convenience instance
formatter = JiraFormatter()
