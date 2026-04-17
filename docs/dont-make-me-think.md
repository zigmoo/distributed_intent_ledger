---
name: Don't Make Me Think — low-inference design principle
description: Config files, error messages, help output, TUI displays, and handoffs should be immediately actionable without requiring the reader to infer, search, or cross-reference
type: feedback
---

"Don't make me think" applies to everything the user or agent reads or acts on.

DIL pushes this principle further: when assistants are unreliable, the system should reduce reliance on inference to the maximum extent possible. Prefer explicit commands, durable artifacts, deterministic scripts, typed schemas, and validated handoffs over free-form model consistency.

**Why:** The reader shouldn't have to map a concept to a command name, guess the next step, or reconstruct missing context from scattered files.

**How to apply:**
- Config files: show the literal tool name, the override file path, and all available settings with defaults commented out
- Error messages: show exact copy-paste commands to fix the problem, not "check the docs"
- Help output: show config file locations, not just flag descriptions
- Auto-create stub configs on first failure with documented defaults
- TUI/reports: show clickable URLs, not bare ticket IDs
- Log files: show the log path in the log itself
- Handoffs: list verified paths, prerequisites, unresolved questions, and the exact next action
- Every output should answer "what do I do next?" without the reader leaving the screen
- Code: variable names, function names, method names, and comments should be self-documenting — a reader should understand intent without tracing call chains or reading external docs
