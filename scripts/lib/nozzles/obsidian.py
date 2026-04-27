"""Obsidian-flavored Markdown formatter.

Produces output compatible with Obsidian's extended Markdown dialect,
including callout blocks, wiki-links, and YAML frontmatter.

Usage:
    from formatters.obsidian import formatter

    lines = [
        formatter.title("Meeting Summary"),
        formatter.header("Cloud Migration"),
        formatter.bullet("82 jobs remaining"),
    ]
    print(formatter.wrap(formatter.join(lines), title="Meeting Summary"))
"""

from datetime import date
from typing import List

from nozzles.base import BaseFormatter

# Characters that have special meaning in Markdown and need escaping.
_SPECIAL_CHARS = r"\`*_{}[]()#+-.!|~>"


class ObsidianFormatter(BaseFormatter):
    """Formatter targeting Obsidian vaults (extended Markdown)."""

    # -- Headings --------------------------------------------------------

    def title(self, text: str) -> str:
        return f"# {text}"

    def header(self, text: str) -> str:
        return f"## {text}"

    def subheader(self, text: str) -> str:
        return f"### {text}"

    # -- Lists -----------------------------------------------------------

    def bullet(self, text: str) -> str:
        return f"- {text}"

    def numbered(self, n: int, text: str) -> str:
        return f"{n}. {text}"

    # -- Inline formatting -----------------------------------------------

    def bold(self, text: str) -> str:
        return f"**{text}**"

    def italic(self, text: str) -> str:
        return f"*{text}*"

    def code(self, text: str) -> str:
        return f"`{text}`"

    # -- Blocks ----------------------------------------------------------

    def code_block(self, text: str, language: str = "") -> str:
        return f"```{language}\n{text}\n```"

    def meta(self, text: str) -> str:
        return f"> {text}"

    def panel(self, text: str, title: str = "", style: str = "info") -> str:
        """Obsidian callout block.

        Maps generic style names to Obsidian callout types:
            info    -> [!info]
            warning -> [!caution]
            error   -> [!danger]
            success -> [!tip]
        """
        style_map = {
            "info": "info",
            "warning": "caution",
            "error": "danger",
            "success": "tip",
        }
        callout_type = style_map.get(style, style)
        header_line = f"> [!{callout_type}] {title}" if title else f"> [!{callout_type}]"
        body_lines = "\n".join(f"> {line}" for line in text.split("\n"))
        return f"{header_line}\n{body_lines}"

    def milestone(self, text: str) -> str:
        return f"- ✅ {text}"

    # -- Links -----------------------------------------------------------

    def link(self, text: str, url: str) -> str:
        """Standard markdown link for external URLs.

        For internal/wiki-links pass an empty url and the text will be
        rendered as ``[[text]]``.
        """
        if not url:
            return f"[[{text}]]"
        return f"[{text}]({url})"

    # -- Structural ------------------------------------------------------

    def separator(self) -> str:
        return "---"

    def spacer(self) -> str:
        return ""

    def table(self, headers: List[str], rows: List[List[str]]) -> str:
        header_row = "| " + " | ".join(headers) + " |"
        align_row = "| " + " | ".join("---" for _ in headers) + " |"
        data_rows = "\n".join(
            "| " + " | ".join(row) + " |" for row in rows
        )
        return f"{header_row}\n{align_row}\n{data_rows}"

    # -- Escaping --------------------------------------------------------

    def escape(self, text: str) -> str:
        result = []
        for ch in text:
            if ch in _SPECIAL_CHARS:
                result.append(f"\\{ch}")
            else:
                result.append(ch)
        return "".join(result)

    # -- Document-level --------------------------------------------------

    def wrap(self, body: str, title: str = "") -> str:
        """Optionally prepend YAML frontmatter when a title is provided."""
        if not title:
            return body
        today = date.today().isoformat()
        frontmatter = (
            "---\n"
            f'title: "{title}"\n'
            f"date: {today}\n"
            "tags: [meeting-notes]\n"
            "type: meeting-notes\n"
            "---"
        )
        return f"{frontmatter}\n\n{body}"

    def join(self, lines: List[str]) -> str:
        return "\n".join(lines)


# Module-level convenience instance.
formatter = ObsidianFormatter()
