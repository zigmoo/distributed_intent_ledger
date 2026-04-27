"""HTML formatter — standalone web page with CSS classes."""

from typing import List
from .base import BaseFormatter


class HtmlFormatter(BaseFormatter):
    """Renders content as HTML with CSS classes for standalone pages."""

    def title(self, text: str) -> str:
        return f'<h1 class="fmt-title">{self.escape(text)}</h1>'

    def header(self, text: str) -> str:
        return f'<h3 class="fmt-section">{self.escape(text)}</h3>'

    def subheader(self, text: str) -> str:
        return f'<h4 class="fmt-subsection">{self.escape(text)}</h4>'

    def bullet(self, text: str) -> str:
        return f"<li>{text}</li>"

    def numbered(self, n: int, text: str) -> str:
        return f"<li>{text}</li>"

    def bold(self, text: str) -> str:
        return f"<strong>{text}</strong>"

    def italic(self, text: str) -> str:
        return f"<em>{text}</em>"

    def code(self, text: str) -> str:
        return f"<code>{self.escape(text)}</code>"

    def code_block(self, text: str, language: str = "") -> str:
        lang_class = f' class="{self.escape(language)}"' if language else ""
        return f"<pre><code{lang_class}>{self.escape(text)}</code></pre>"

    def meta(self, text: str) -> str:
        return f'<p class="fmt-meta">{text}</p>'

    def link(self, text: str, url: str) -> str:
        return f'<a href="{self.escape(url)}">{self.escape(text)}</a>'

    def milestone(self, text: str) -> str:
        return f'<li class="fmt-milestone">\U0001f3c6 {text}</li>'

    def separator(self) -> str:
        return "<hr>"

    def spacer(self) -> str:
        return ""

    def table(self, headers: List[str], rows: List[List[str]]) -> str:
        parts = ['<table class="fmt-table">']
        parts.append("<thead><tr>")
        for h in headers:
            parts.append(f"<th>{self.escape(h)}</th>")
        parts.append("</tr></thead>")
        parts.append("<tbody>")
        for row in rows:
            parts.append("<tr>")
            for cell in row:
                parts.append(f"<td>{self.escape(cell)}</td>")
            parts.append("</tr>")
        parts.append("</tbody></table>")
        return "".join(parts)

    def panel(self, text: str, title: str = "", style: str = "info") -> str:
        title_div = (
            f'<div class="fmt-panel-title">{self.escape(title)}</div>'
            if title
            else ""
        )
        return (
            f'<div class="fmt-panel fmt-panel-{self.escape(style)}">'
            f"{title_div}{text}</div>"
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
        safe_title = self.escape(title) if title else "Document"
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title}</title>
<style>
  :root {{
    --accent: #1a73e8;
    --text: #222;
    --text-light: #666;
    --bg: #fff;
    --border: #e0e0e0;
    --code-bg: #f5f5f5;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 Helvetica, Arial, sans-serif;
    font-size: 15px;
    line-height: 1.6;
    color: var(--text);
    background: var(--bg);
    max-width: 800px;
    margin: 0 auto;
    padding: 32px 24px;
  }}
  .fmt-title {{
    color: var(--accent);
    font-size: 1.8em;
    border-bottom: 3px solid var(--accent);
    padding-bottom: 8px;
    margin-bottom: 16px;
  }}
  .fmt-section {{
    color: var(--text);
    margin-top: 24px;
    margin-bottom: 8px;
    font-size: 1.25em;
  }}
  .fmt-subsection {{
    color: var(--text);
    margin-top: 16px;
    margin-bottom: 4px;
    font-size: 1.1em;
  }}
  .fmt-meta {{
    color: var(--text-light);
    font-style: italic;
    margin-bottom: 8px;
  }}
  .fmt-milestone {{
    list-style: none;
    font-weight: 600;
    color: var(--accent);
    margin: 4px 0;
  }}
  .fmt-table {{
    border-collapse: collapse;
    width: 100%;
    margin: 12px 0;
  }}
  .fmt-table th, .fmt-table td {{
    border: 1px solid var(--border);
    padding: 8px 12px;
    text-align: left;
  }}
  .fmt-table th {{
    background: var(--code-bg);
    font-weight: 600;
  }}
  .fmt-table tr:nth-child(even) {{
    background: #fafafa;
  }}
  .fmt-panel {{
    border-radius: 6px;
    padding: 12px 16px;
    margin: 12px 0;
    border-left: 4px solid;
  }}
  .fmt-panel-title {{
    font-weight: 700;
    margin-bottom: 4px;
  }}
  .fmt-panel-info  {{ border-color: #1a73e8; background: #e8f0fe; }}
  .fmt-panel-warning {{ border-color: #f9a825; background: #fff8e1; }}
  .fmt-panel-error   {{ border-color: #d32f2f; background: #fde7e7; }}
  .fmt-panel-success {{ border-color: #2e7d32; background: #e8f5e9; }}
  ul, ol {{ margin: 8px 0 8px 24px; }}
  li {{ margin: 2px 0; }}
  code {{
    background: var(--code-bg);
    padding: 2px 5px;
    border-radius: 3px;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 0.9em;
  }}
  pre {{
    background: var(--code-bg);
    padding: 12px 16px;
    border-radius: 6px;
    overflow-x: auto;
    margin: 12px 0;
  }}
  pre code {{
    background: none;
    padding: 0;
  }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  hr {{
    border: none;
    border-top: 1px solid var(--border);
    margin: 20px 0;
  }}
  strong {{ font-weight: 600; }}
</style>
</head>
<body>
{body}
</body>
</html>"""

    def join(self, lines: List[str]) -> str:
        return "\n".join(lines)


formatter = HtmlFormatter()
