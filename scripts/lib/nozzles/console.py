"""Console formatter — colorized terminal output with ANSI escape codes."""

import re
from typing import List

from .base import BaseFormatter


# ANSI color codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
WHITE = "\033[97m"
MAGENTA = "\033[35m"
RED = "\033[31m"

# Strip pattern for existing ANSI codes
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

# Panel border colors by style
_PANEL_COLORS = {
    "info": CYAN,
    "warning": YELLOW,
    "error": RED,
    "success": GREEN,
}


class ConsoleFormatter(BaseFormatter):
    """ANSI-colorized terminal output."""

    def title(self, text: str) -> str:
        bar = "━" * 5
        return f"{BOLD}{CYAN}{bar}  {text}  {bar}{RESET}"

    def header(self, text: str) -> str:
        bar = "━━"
        return f"{BOLD}{YELLOW}{bar} {text} {bar}{RESET}"

    def subheader(self, text: str) -> str:
        return f"  {BOLD}{WHITE}▸ {text}{RESET}"

    def bullet(self, text: str) -> str:
        return f"  {DIM}•{RESET} {text}"

    def numbered(self, n: int, text: str) -> str:
        return f"  {GREEN}{n}.{RESET} {text}"

    def bold(self, text: str) -> str:
        return f"{BOLD}{text}{RESET}"

    def italic(self, text: str) -> str:
        return f"{DIM}{text}{RESET}"

    def code(self, text: str) -> str:
        return f"`{text}`"

    def code_block(self, text: str, language: str = "") -> str:
        lines = text.splitlines()
        indented = "\n".join(f"    {DIM}{line}{RESET}" for line in lines)
        return indented

    def meta(self, text: str) -> str:
        return f"  {DIM}{text}{RESET}"

    def link(self, text: str, url: str) -> str:
        return f"{CYAN}{text} ({url}){RESET}"

    def milestone(self, text: str) -> str:
        return f"  {MAGENTA}★{RESET} {text}"

    def separator(self) -> str:
        return f"{DIM}{'─' * 60}{RESET}"

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
            return f" │ ".join(cells)

        # Header
        header_line = f" {BOLD}{fmt_row(headers)}{RESET}"
        sep_line = f"{'─' * (sum(widths) + 3 * (col_count - 1))}"
        # Data rows
        data_lines = [f" {fmt_row(r)}" for r in rows]
        return "\n".join([header_line, sep_line] + data_lines)

    def panel(self, text: str, title: str = "", style: str = "info") -> str:
        color = _PANEL_COLORS.get(style, CYAN)
        lines = text.splitlines()
        result = []
        if title:
            result.append(f"{color}┃{RESET} {BOLD}{title}{RESET}")
        for line in lines:
            result.append(f"{color}┃{RESET} {line}")
        return "\n".join(result)

    def escape(self, text: str) -> str:
        return _ANSI_RE.sub("", text)

    def wrap(self, body: str, title: str = "") -> str:
        return body


formatter = ConsoleFormatter()
