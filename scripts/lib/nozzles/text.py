"""Text formatter — plain text output with zero decoration or color codes."""

from typing import List

from .base import BaseFormatter


class TextFormatter(BaseFormatter):
    """Plain-text output with no ANSI codes or markup."""

    def title(self, text: str) -> str:
        return f"=====  {text}  ====="

    def header(self, text: str) -> str:
        return f"--- {text} ---"

    def subheader(self, text: str) -> str:
        return f"  > {text}"

    def bullet(self, text: str) -> str:
        return f"  * {text}"

    def numbered(self, n: int, text: str) -> str:
        return f"  {n}. {text}"

    def bold(self, text: str) -> str:
        return text.upper()

    def italic(self, text: str) -> str:
        return text

    def code(self, text: str) -> str:
        return f"`{text}`"

    def code_block(self, text: str, language: str = "") -> str:
        lines = text.splitlines()
        return "\n".join(f"    {line}" for line in lines)

    def meta(self, text: str) -> str:
        return f"  {text}"

    def link(self, text: str, url: str) -> str:
        return f"{text} ({url})"

    def milestone(self, text: str) -> str:
        return f"  [*] {text}"

    def separator(self) -> str:
        return "-" * 60

    def spacer(self) -> str:
        return ""

    def table(self, headers: List[str], rows: List[List[str]]) -> str:
        # Calculate column widths
        all_rows = [headers] + rows
        col_count = len(headers)
        widths = [0] * col_count
        for row in all_rows:
            for i, cell in enumerate(row[:col_count]):
                widths[i] = max(widths[i], len(str(cell)))

        def fmt_row(row):
            cells = []
            for i in range(col_count):
                val = str(row[i]) if i < len(row) else ""
                cells.append(val.ljust(widths[i]))
            return "  ".join(cells)

        header_line = fmt_row(headers)
        sep_line = "-" * (sum(widths) + 2 * (col_count - 1))
        data_lines = [fmt_row(r) for r in rows]
        return "\n".join([header_line, sep_line] + data_lines)

    def panel(self, text: str, title: str = "", style: str = "info") -> str:
        lines = text.splitlines()
        result = []
        if title:
            result.append(f"| {title}")
        for line in lines:
            result.append(f"| {line}")
        return "\n".join(result)

    def escape(self, text: str) -> str:
        return text

    def wrap(self, body: str, title: str = "") -> str:
        return body


formatter = TextFormatter()
