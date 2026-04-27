"""GitLab-flavored Markdown formatter."""

import re
from typing import List

from .base import BaseFormatter

_MD_SPECIAL = re.compile(r"([\\`*_{}[\]()#+\-.!|~>])")


class GitLabFormatter(BaseFormatter):
    """Render output as GitLab-flavored Markdown."""

    # ── escaping ──────────────────────────────────────────────────────

    def escape(self, text: str) -> str:
        """Backslash-escape Markdown special characters."""
        return _MD_SPECIAL.sub(r"\\\1", text)

    # ── block elements ────────────────────────────────────────────────

    def title(self, text: str) -> str:
        return f"# {text}"

    def header(self, text: str) -> str:
        return f"## {text}"

    def subheader(self, text: str) -> str:
        return f"### {text}"

    def bullet(self, text: str) -> str:
        return f"- {text}"

    def numbered(self, n: int, text: str) -> str:
        return f"{n}. {text}"

    def meta(self, text: str) -> str:
        return f"*{text}*"

    def separator(self) -> str:
        return "---"

    def spacer(self) -> str:
        return ""

    # ── inline elements ───────────────────────────────────────────────

    def bold(self, text: str) -> str:
        return f"**{text}**"

    def italic(self, text: str) -> str:
        return f"_{text}_"

    def code(self, text: str) -> str:
        return f"`{text}`"

    def code_block(self, text: str, language: str = "") -> str:
        return f"```{language}\n{text}\n```"

    def link(self, text: str, url: str) -> str:
        return f"[{text}]({url})"

    def milestone(self, text: str) -> str:
        return f"- ✅ {text}"

    # ── composite elements ────────────────────────────────────────────

    def table(self, headers: List[str], rows: List[List[str]]) -> str:
        header_line = "| " + " | ".join(headers) + " |"
        sep_line = "| " + " | ".join("---" for _ in headers) + " |"
        data_lines = [
            "| " + " | ".join(str(c) for c in row) + " |"
            for row in rows
        ]
        return "\n".join([header_line, sep_line, *data_lines])

    def panel(self, text: str, title: str = "", style: str = "info") -> str:
        emoji = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "success": "✅",
        }.get(style, "ℹ️")
        label = {
            "info": "Info",
            "warning": "Warning",
            "error": "Error",
            "success": "Success",
        }.get(style, "Info")
        heading = f"{emoji} **{title or label}:** " if title else f"{emoji} **{label}:** "
        lines = text.split("\n")
        return "\n".join(f"> {heading}{lines[0]}" if i == 0 else f"> {line}"
                         for i, line in enumerate(lines))

    # ── GitLab-specific helpers ───────────────────────────────────────

    @staticmethod
    def collapsible(summary: str, content: str) -> str:
        """GitLab collapsible section via <details>/<summary>."""
        return f"<details><summary>{summary}</summary>\n\n{content}\n\n</details>"

    @staticmethod
    def task_list(items: List[tuple[bool, str]]) -> str:
        """Render a task list. items: list of (checked, text) tuples."""
        return "\n".join(
            f"- [{'x' if done else ' '}] {text}"
            for done, text in items
        )

    # ── document wrapper ──────────────────────────────────────────────

    def wrap(self, body: str, title: str = "") -> str:
        return body


formatter = GitLabFormatter()
