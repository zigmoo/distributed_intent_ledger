"""Base formatter interface — all formatters implement these functions."""

from abc import ABC, abstractmethod
from typing import List, Optional


class BaseFormatter(ABC):
    """Common interface for all platform formatters.

    Every formatter must implement these methods. Platform-specific
    idiosyncrasies are handled inside each implementation.
    """

    @abstractmethod
    def title(self, text: str) -> str:
        """Top-level document title."""

    @abstractmethod
    def header(self, text: str) -> str:
        """Section header."""

    @abstractmethod
    def subheader(self, text: str) -> str:
        """Sub-section header."""

    @abstractmethod
    def bullet(self, text: str) -> str:
        """Unordered list item."""

    @abstractmethod
    def numbered(self, n: int, text: str) -> str:
        """Ordered list item."""

    @abstractmethod
    def bold(self, text: str) -> str:
        """Bold/strong text inline."""

    @abstractmethod
    def italic(self, text: str) -> str:
        """Italic/emphasis text inline."""

    @abstractmethod
    def code(self, text: str) -> str:
        """Inline code."""

    @abstractmethod
    def code_block(self, text: str, language: str = "") -> str:
        """Multi-line code/preformatted block."""

    @abstractmethod
    def meta(self, text: str) -> str:
        """Metadata line (date, attendees, etc.) — usually subdued styling."""

    @abstractmethod
    def link(self, text: str, url: str) -> str:
        """Hyperlink."""

    @abstractmethod
    def milestone(self, text: str) -> str:
        """Milestone/achievement item — visually distinct from regular bullets."""

    @abstractmethod
    def separator(self) -> str:
        """Horizontal rule / section divider."""

    @abstractmethod
    def spacer(self) -> str:
        """Blank line / vertical spacing."""

    @abstractmethod
    def table(self, headers: List[str], rows: List[List[str]]) -> str:
        """Formatted table."""

    @abstractmethod
    def panel(self, text: str, title: str = "", style: str = "info") -> str:
        """Callout/panel/admonition block. style: info, warning, error, success."""

    @abstractmethod
    def escape(self, text: str) -> str:
        """Escape special characters for this platform."""

    def wrap(self, body: str, title: str = "") -> str:
        """Optional wrapper (HTML page, RTF envelope, frontmatter, etc.).
        Default: return body unchanged."""
        return body

    def join(self, lines: List[str]) -> str:
        """Join formatted lines into final output. Default: newline join."""
        return "\n".join(lines)
