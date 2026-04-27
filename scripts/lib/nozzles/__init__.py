"""Shared formatter library — platform-aware output rendering.

Usage:
    from nozzles import jira, teams, obsidian

    output = jira.title("Meeting Summary")
    output += jira.header("Cloud Migration")
    output += jira.bullet("82 jobs remaining")
    output += jira.wrap(output)  # adds platform-specific wrapper
"""

from pathlib import Path

FORMATTER_DIR = Path(__file__).parent
AVAILABLE = [
    "jira", "smax", "gitlab", "github", "obsidian",
    "teams", "rtf", "html", "email", "console", "text",
]
