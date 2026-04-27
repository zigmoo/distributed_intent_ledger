"""X post formatter — plain text with character-count awareness for X/Twitter."""

import re
from typing import List

from .base import BaseFormatter


class XPostFormatter(BaseFormatter):
    """Plain-text formatter for X posts. No markup, 280-char aware."""

    MAX_CHARS = 280
    URL_DISPLAY_LENGTH = 23
    URL_PATTERN = re.compile(r"https?://\S+")

    def title(self, text: str) -> str:
        return text

    def header(self, text: str) -> str:
        return text

    def subheader(self, text: str) -> str:
        return text

    def bullet(self, text: str) -> str:
        return f"- {text}"

    def numbered(self, n: int, text: str) -> str:
        return f"{n}. {text}"

    def bold(self, text: str) -> str:
        return text

    def italic(self, text: str) -> str:
        return text

    def code(self, text: str) -> str:
        return text

    def code_block(self, text: str, language: str = "") -> str:
        return text

    def meta(self, text: str) -> str:
        return text

    def link(self, text: str, url: str) -> str:
        return url

    def milestone(self, text: str) -> str:
        return f"- {text}"

    def separator(self) -> str:
        return ""

    def spacer(self) -> str:
        return ""

    def table(self, headers: List[str], rows: List[List[str]]) -> str:
        col_count = len(headers)
        all_rows = [headers] + rows
        widths = [0] * col_count
        for row in all_rows:
            for i, cell in enumerate(row[:col_count]):
                widths[i] = max(widths[i], len(str(cell)))

        def fmt(row):
            cells = []
            for i in range(col_count):
                val = str(row[i]) if i < len(row) else ""
                cells.append(val.ljust(widths[i]))
            return " | ".join(cells)

        return "\n".join(fmt(r) for r in all_rows)

    def panel(self, text: str, title: str = "", style: str = "info") -> str:
        if title:
            return f"{title}: {text}"
        return text

    def escape(self, text: str) -> str:
        return text

    def count_chars(self, text: str) -> int:
        """Count characters as X does: URLs count as 23 chars regardless of length."""
        urls = self.URL_PATTERN.findall(text)
        stripped = text
        for url in urls:
            stripped = stripped.replace(url, "", 1)
        return len(stripped) + len(urls) * self.URL_DISPLAY_LENGTH

    def wrap(self, body: str, title: str = "") -> str:
        """Validate character count. Warn if over limit but do NOT truncate."""
        char_count = self.count_chars(body)
        if char_count > self.MAX_CHARS:
            return (
                f"WARN | {char_count} chars exceeds {self.MAX_CHARS} limit "
                f"(over by {char_count - self.MAX_CHARS})\n\n{body}"
            )
        remaining = self.MAX_CHARS - char_count
        return f"{body}\n\n[{remaining} chars remaining]"


formatter = XPostFormatter()
