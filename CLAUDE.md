# superRepo

Read `AGENTS.md` (ownership, verification checklist, integration gaps) and then `system/README.md`
(the shared operating structure). Both apply to every agent here; this file adds nothing of its own.

Claude Code is the implementation owner of this repository; Codex coordinates and verifies. The
Conversationalist is the only user-facing role; the Coordinator (`tools/coordinator.py`) is the only
writer of `workflow/`; the watchdog is independent of both. Canonical role and skill text lives in
`system/agents/` and `system/skills/`; `.claude/agents/` and `.claude/skills/` are thin pointers.

Nothing is committed, pushed, scheduled as a service or added to a settings file without William's
explicit word for that action. Domain content and `sessions/` stay out of this repository.
