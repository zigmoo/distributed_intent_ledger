"""Email formatter — HTML with all inline CSS for email client compatibility."""

from typing import List
from .base import BaseFormatter


class EmailFormatter(BaseFormatter):
    """Renders content as HTML with inline styles for email clients."""

    def title(self, text: str) -> str:
        return (
            f'<h2 style="color:#1a73e8;border-bottom:2px solid #1a73e8;'
            f'padding-bottom:6px;">{self.escape(text)}</h2>'
        )

    def header(self, text: str) -> str:
        return (
            f'<h3 style="color:#333;margin-top:16px;margin-bottom:4px;">'
            f"{self.escape(text)}</h3>"
        )

    def subheader(self, text: str) -> str:
        return (
            f'<h4 style="color:#555;margin-top:12px;margin-bottom:2px;'
            f'font-size:14px;">{self.escape(text)}</h4>'
        )

    def bullet(self, text: str) -> str:
        return f'<div style="margin-left:16px;">&#8226; {text}</div>'

    def numbered(self, n: int, text: str) -> str:
        return f'<div style="margin-left:16px;">{n}. {text}</div>'

    def bold(self, text: str) -> str:
        return f"<strong>{text}</strong>"

    def italic(self, text: str) -> str:
        return f"<em>{text}</em>"

    def code(self, text: str) -> str:
        return (
            f'<code style="background:#f5f5f5;padding:1px 4px;'
            f'border-radius:3px;font-family:Consolas,monospace;'
            f'font-size:13px;">{self.escape(text)}</code>'
        )

    def code_block(self, text: str, language: str = "") -> str:
        return (
            f'<pre style="background:#f5f5f5;padding:12px;border-radius:4px;'
            f'font-family:Consolas,monospace;font-size:13px;">'
            f"{self.escape(text)}</pre>"
        )

    def meta(self, text: str) -> str:
        return (
            f'<div style="color:#666;font-style:italic;margin-bottom:8px;">'
            f"{text}</div>"
        )

    def link(self, text: str, url: str) -> str:
        return (
            f'<a href="{self.escape(url)}" style="color:#1a73e8;">'
            f"{self.escape(text)}</a>"
        )

    def milestone(self, text: str) -> str:
        return (
            f'<div style="margin-left:16px;font-weight:bold;color:#1a73e8;">'
            f"\U0001f3c6 {text}</div>"
        )

    def separator(self) -> str:
        return '<hr style="border:none;border-top:1px solid #e0e0e0;margin:16px 0;">'

    def spacer(self) -> str:
        return "<br>"

    def table(self, headers: List[str], rows: List[List[str]]) -> str:
        parts = [
            '<table style="border-collapse:collapse;width:100%;margin:12px 0;">'
        ]
        parts.append("<tr>")
        for h in headers:
            parts.append(
                f'<th style="border:1px solid #ddd;padding:8px 12px;'
                f'text-align:left;background:#f5f5f5;font-weight:600;">'
                f"{self.escape(h)}</th>"
            )
        parts.append("</tr>")
        for i, row in enumerate(rows):
            bg = "#ffffff" if i % 2 == 0 else "#fafafa"
            parts.append(f"<tr>")
            for cell in row:
                parts.append(
                    f'<td style="border:1px solid #ddd;padding:8px 12px;'
                    f'background:{bg};">{self.escape(cell)}</td>'
                )
            parts.append("</tr>")
        parts.append("</table>")
        return "".join(parts)

    def panel(self, text: str, title: str = "", style: str = "info") -> str:
        colors = {
            "info":    ("#1a73e8", "#e8f0fe"),
            "warning": ("#f9a825", "#fff8e1"),
            "error":   ("#d32f2f", "#fde7e7"),
            "success": ("#2e7d32", "#e8f5e9"),
        }
        border_color, bg_color = colors.get(style, colors["info"])
        title_div = (
            f'<div style="font-weight:bold;margin-bottom:4px;">'
            f"{self.escape(title)}</div>"
            if title
            else ""
        )
        return (
            f'<div style="border-left:4px solid {border_color};'
            f"background:{bg_color};padding:12px 16px;margin:12px 0;"
            f'border-radius:4px;">{title_div}{text}</div>'
        )

    def escape(self, text: str) -> str:
        return (
            str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    def wrap(self, body: str, title: str = "") -> str:
        safe_title = self.escape(title) if title else "Message"
        return (
            f"<!DOCTYPE html>\n"
            f'<html lang="en">\n<head>\n'
            f'<meta charset="utf-8">\n'
            f"<title>{safe_title}</title>\n"
            f"</head>\n"
            f'<body style="font-family:Calibri,\'Segoe UI\',sans-serif;'
            f"font-size:14px;color:#333;max-width:700px;"
            f'margin:0 auto;padding:16px;">\n'
            f"{body}\n"
            f'<div style="margin-top:24px;padding-top:12px;'
            f"border-top:1px solid #e0e0e0;color:#999;"
            f'font-size:11px;">[⚙ email]</div>\n'
            f"</body>\n</html>"
        )

    def join(self, lines: List[str]) -> str:
        return "\n".join(lines)


formatter = EmailFormatter()
