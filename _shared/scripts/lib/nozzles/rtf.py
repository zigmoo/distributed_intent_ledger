"""RTF (Rich Text Format) formatter."""

from typing import List

from .base import BaseFormatter


class RtfFormatter(BaseFormatter):
    """Render output as RTF markup."""

    # ── escaping ──────────────────────────────────────────────────────

    def escape(self, text: str) -> str:
        """Escape special RTF characters and non-ASCII to \\uNNNN?."""
        out: list[str] = []
        for ch in text:
            if ch == "\\":
                out.append("\\\\")
            elif ch == "{":
                out.append("\\{")
            elif ch == "}":
                out.append("\\}")
            elif ord(ch) > 127:
                out.append(f"\\u{ord(ch)}?")
            else:
                out.append(ch)
        return "".join(out)

    # ── block elements ────────────────────────────────────────────────

    def title(self, text: str) -> str:
        return f"\\pard\\b\\fs32 {self.escape(text)}\\b0\\par"

    def header(self, text: str) -> str:
        return f"\\par\\pard\\b\\fs24 {self.escape(text)}\\b0\\par"

    def subheader(self, text: str) -> str:
        return f"\\par\\pard\\b\\fs22 {self.escape(text)}\\b0\\par"

    def bullet(self, text: str) -> str:
        return f"\\par\\pard\\li360 \\bullet  {self.escape(text)}"

    def numbered(self, n: int, text: str) -> str:
        return f"\\par\\pard\\li360 {n}. {self.escape(text)}"

    def meta(self, text: str) -> str:
        return f"\\pard\\i\\fs20 {self.escape(text)}\\i0\\par"

    def separator(self) -> str:
        return "\\par\\pard\\brdrb\\brdrs\\brdrw10\\brsp20\\par"

    def spacer(self) -> str:
        return "\\par"

    # ── inline elements ───────────────────────────────────────────────

    def bold(self, text: str) -> str:
        return f"\\b {self.escape(text)}\\b0 "

    def italic(self, text: str) -> str:
        return f"\\i {self.escape(text)}\\i0 "

    def code(self, text: str) -> str:
        return f"{{\\f1 {self.escape(text)}}}"

    def code_block(self, text: str, language: str = "") -> str:
        return f"{{\\f1\\fs18 {self.escape(text)}}}"

    def link(self, text: str, url: str) -> str:
        return self.escape(text)

    def milestone(self, text: str) -> str:
        return f"\\par\\pard\\li360 \\u10004? {self.escape(text)}"

    # ── composite elements ────────────────────────────────────────────

    def table(self, headers: List[str], rows: List[List[str]]) -> str:
        col_count = len(headers)
        col_width = 2000  # twips per column

        parts: list[str] = []

        # header row
        parts.append("\\trowd")
        for i in range(1, col_count + 1):
            parts.append(f"\\cellx{i * col_width}")
        for h in headers:
            parts.append(f"\\b {self.escape(h)}\\b0\\cell")
        parts.append("\\row")

        # data rows
        for row in rows:
            parts.append("\\trowd")
            for i in range(1, col_count + 1):
                parts.append(f"\\cellx{i * col_width}")
            for cell in row:
                parts.append(f"{self.escape(str(cell))}\\cell")
            parts.append("\\row")

        return "\n".join(parts)

    def panel(self, text: str, title: str = "", style: str = "info") -> str:
        color_idx = {
            "info": 1,      # blue
            "warning": 2,   # dark gray (reuse slot)
            "error": 2,     # dark gray
            "success": 3,   # green
        }.get(style, 1)
        heading = f"\\b {self.escape(title)}\\b0\\line " if title else ""
        return (
            f"\\par\\pard\\li360\\brdrl\\brdrs\\brdrw20\\brdrcf{color_idx}\\brsp80 "
            f"{heading}{self.escape(text)}\\par"
        )

    # ── document wrapper ──────────────────────────────────────────────

    def wrap(self, body: str, title: str = "") -> str:
        return (
            "{\\rtf1\\ansi\\deff0"
            "{\\fonttbl{\\f0 Calibri;}{\\f1 Consolas;}}"
            "{\\colortbl;"
            "\\red26\\green115\\blue232;"
            "\\red51\\green51\\blue51;"
            "\\red13\\green124\\blue61;}"
            f"\\f0\\fs22 {body}}}"
        )


formatter = RtfFormatter()
