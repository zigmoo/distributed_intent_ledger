# User Scratchpad

This directory is for the user's personal notes — anything that doesn't fit neatly into tasks, memory notes, or project files. Think of it as a digital junk drawer with purpose.

## What goes here

- **User biography** — synthesized from resumes, LinkedIn profiles, and career history. Useful for agents that need to understand who you are and tailor their assistance.
- **Post-it notes** — quick reference items: phone numbers, paint colors, account numbers, measurements, anything you'd stick on your monitor.
- **Research scratchpads** — working documents, comparisons, cost analyses, draft arguments.
- **Domain-specific notebooks** — notes that span multiple projects or don't belong to any single task.

## User Biography

A good starting point: gather your resumes, LinkedIn exports, and any career history documents into a folder. Ask your agent to synthesize a full biography from them:

```
"Read all the files in ~/resumes/ and synthesize a comprehensive professional biography.
Start from the earliest job and work forward. Include technical skills, leadership roles,
and career transitions. Write it in third person."
```

The result goes in `user_biography.md`. This gives every agent in your ecosystem immediate context about who they're working with — a senior architect gets different answers than a first-year intern.

## Post-it Notes

For quick-reference items, just create a markdown file and dump them in. No frontmatter required. These are for you, not for the protocol.
