# Progress doc (keeps work alive through compaction)

- Near the window limit Claude Code compacts the context: the exact history is gone, a summary replaces it.
- When a task starts, estimate whether it can outgrow the window (long research, many files, several agents). If so, maintain a progress doc from the first step; re-estimate as the task grows and start one the moment it might.
- File: `<repo>-<task-slug>.md` inside `~/.claude/progress/`; `<repo>` is the basename of the working directory, or a domain name for work outside a repo. Contents: goal, decisions made, finished vs open, the next action, file paths. Refresh it after every meaningful step (after compaction, recently changed docs are listed for re-reading).
- A sizable task handed to a subagent or teammate carries the same duty in its prompt, with the exact doc path.
- Hooks back this up in the main session as well as in subagents: orders at two context sizes and one right after compaction. Each is binding: update the doc first, then continue.
