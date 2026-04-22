"""SMAX rich-text formatter (restricted HTML subset)."""

from typing import List

from .base import BaseFormatter


class SmaxFormatter(BaseFormatter):
    """Render output as the HTML subset accepted by SMAX comments."""

    # ── escaping ──────────────────────────────────────────────────────

    def escape(self, text: str) -> str:
        """Escape to HTML entities."""
        return (
            text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    # ── block elements ────────────────────────────────────────────────

    def title(self, text: str) -> str:
        return f"<h2>{self.escape(text)}</h2>"

    def header(self, text: str) -> str:
        return f"<h3>{self.escape(text)}</h3>"

    def subheader(self, text: str) -> str:
        return f"<h4>{self.escape(text)}</h4>"

    def bullet(self, text: str) -> str:
        return f"<li>{self.escape(text)}</li>"

    def numbered(self, n: int, text: str) -> str:
        return f"<li>{self.escape(text)}</li>"

    def meta(self, text: str) -> str:
        return f"<p><i>{self.escape(text)}</i></p>"

    def separator(self) -> str:
        return "<hr>"

    def spacer(self) -> str:
        return "<br>"

    # ── inline elements ───────────────────────────────────────────────

    def bold(self, text: str) -> str:
        return f"<b>{self.escape(text)}</b>"

    def italic(self, text: str) -> str:
        return f"<i>{self.escape(text)}</i>"

    def code(self, text: str) -> str:
        return f"<code>{self.escape(text)}</code>"

    def code_block(self, text: str, language: str = "") -> str:
        return f"<pre>{self.escape(text)}</pre>"

    def link(self, text: str, url: str) -> str:
        return f'<a href="{self.escape(url)}">{self.escape(text)}</a>'

    def milestone(self, text: str) -> str:
        return f"<li>&#10004; {self.escape(text)}</li>"

    # ── composite elements ────────────────────────────────────────────

    def table(self, headers: List[str], rows: List[List[str]]) -> str:
        parts: list[str] = ['<table border="1">']

        # header row
        parts.append("<tr>")
        for h in headers:
            parts.append(f"<th>{self.escape(h)}</th>")
        parts.append("</tr>")

        # data rows
        for row in rows:
            parts.append("<tr>")
            for cell in row:
                parts.append(f"<td>{self.escape(str(cell))}</td>")
            parts.append("</tr>")

        parts.append("</table>")
        return "\n".join(parts)

    def panel(self, text: str, title: str = "", style: str = "info") -> str:
        color = {
            "info": "#1a73e8",
            "warning": "#f9a825",
            "error": "#d32f2f",
            "success": "#0d7c3d",
        }.get(style, "#1a73e8")
        heading = f"<b>{self.escape(title)}</b><br>" if title else ""
        return (
            f'<div style="border-left:4px solid {color};padding:8px;'
            f'background:#f9f9f9;">{heading}{self.escape(text)}</div>'
        )

    # ── document wrapper ──────────────────────────────────────────────

    def wrap(self, body: str, title: str = "") -> str:
        return body


formatter = SmaxFormatter()
