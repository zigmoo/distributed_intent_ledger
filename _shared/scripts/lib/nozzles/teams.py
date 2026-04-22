"""Microsoft Teams chat formatter.

Teams chat has limited markdown support and renders best with emoji
prefixes, bullet characters, and — most critically — blank lines
between every thought.  No wall of text ever.

Usage:
    from formatters.teams import formatter

    lines = [
        formatter.title("Daily Stand-up"),
        formatter.header("Blockers"),
        formatter.bullet("Waiting on API key"),
        formatter.bullet("CI pipeline broken"),
    ]
    print(formatter.join(lines))
"""

from typing import List

from nozzles.base import BaseFormatter


class TeamsFormatter(BaseFormatter):
    """Format output for Microsoft Teams chat messages."""

    # Panel emoji map
    _panel_icons = {
        "info": "ℹ️",       # ℹ️
        "warning": "⚠️",    # ⚠️
        "error": "❌",            # ❌
        "success": "✅",          # ✅
    }

    def title(self, text: str) -> str:
        return f"\U0001f4cb {text}"

    def header(self, text: str) -> str:
        return f"\n\U0001f4cc {text}"

    def subheader(self, text: str) -> str:
        return f"▸ {text}"

    def bullet(self, text: str) -> str:
        return f"• {text}"

    def numbered(self, n: int, text: str) -> str:
        return f"{n}. {text}"

    def bold(self, text: str) -> str:
        return text

    def italic(self, text: str) -> str:
        return text

    def code(self, text: str) -> str:
        return f"`{text}`"

    def code_block(self, text: str, language: str = "") -> str:
        return f"```\n{text}\n```"

    def meta(self, text: str) -> str:
        return text

    def link(self, text: str, url: str) -> str:
        return url

    def milestone(self, text: str) -> str:
        return f"\U0001f3c6 {text}"

    def separator(self) -> str:
        return ""

    def spacer(self) -> str:
        return ""

    def table(self, headers: List[str], rows: List[List[str]]) -> str:
        """Render table as aligned bullet list (tables render poorly in Teams chat)."""
        lines = []
        for row in rows:
            parts = []
            for i, cell in enumerate(row):
                label = headers[i] if i < len(headers) else ""
                if label:
                    parts.append(f"{label}: {cell}")
                else:
                    parts.append(cell)
            lines.append(f"• {' | '.join(parts)}")
        return "\n".join(lines)

    def panel(self, text: str, title: str = "", style: str = "info") -> str:
        icon = self._panel_icons.get(style, self._panel_icons["info"])
        if title:
            return f"{icon} {title}: {text}"
        return f"{icon} {text}"

    def escape(self, text: str) -> str:
        return text

    def wrap(self, body: str, title: str = "") -> str:
        return body

    def join(self, lines: List[str]) -> str:
        return "\n".join(lines)

    def to_clipboard(self, lines: List[str], title: str = "") -> str:
        """Render through email nozzle and copy to clipboard as HTML.
        This is the proven path for Teams paste: email HTML → wl-copy --type text/html → Ctrl+V."""
        import subprocess
        from nozzles.email import formatter as email_fmt

        email_lines = []
        for line in lines:
            # Re-render through email nozzle preserving structure
            email_lines.append(line)

        body = email_fmt.join(lines)
        html = email_fmt.wrap(body, title).replace(
            "[⚙ email]", "[⚙ teams]"
        )

        proc = subprocess.run(
            ["wl-copy", "--type", "text/html"],
            input=html, text=True, capture_output=True
        )
        if proc.returncode == 0:
            return "Copied to clipboard as HTML [⚙ teams] — Ctrl+V into Teams"
        return f"wl-copy failed: {proc.stderr}"


formatter = TeamsFormatter()
