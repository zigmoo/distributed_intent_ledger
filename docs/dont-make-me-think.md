---
name: Don't Make Me Think — config and UI design principle
description: All config files, error messages, help output, and TUI displays must be immediately actionable without requiring the reader to infer, search, or cross-reference
type: feedback
---

"Don't make me think" applies to everything the user or agent reads:

**Why:** The user explicitly called this out when a config file listed section names like "Jira" without showing the literal tool name `jira_tool` or the override file path. The reader shouldn't have to map a concept to a command name.

**How to apply:**
- Config files: show the literal tool name, the override file path, and all available settings with defaults commented out
- Error messages: show exact copy-paste commands to fix the problem, not "check the docs"
- Help output: show config file locations, not just flag descriptions
- Auto-create stub configs on first failure with documented defaults
- TUI/reports: show clickable URLs, not bare ticket IDs
- Log files: show the log path in the log itself
- Every output should answer "what do I do next?" without the reader leaving the screen
- Code: variable names, function names, method names, and comments should be self-documenting — a reader should understand intent without tracing call chains or reading external docs
