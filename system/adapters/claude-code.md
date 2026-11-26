# Claude Code adapter

Read root `CLAUDE.md` and `AGENTS.md`, then `system/README.md`. Apply local section
rules to the paths you edit. Shared requirements remain independent of this tool.

Record the tool as `claude-code`. Read only relevant `.claude/skills/` workflows
through `system/skills/README.md`; the newer learning architecture supersedes
their learned-state, probe, and learning-check-in machinery.

Keep durable user corrections in their shared canonical location. Tool-local
memory may hold host-specific observations and links; it must not become the
only copy of a project decision. Do not infer the exact model from the tool name.

Agents in `.claude/agents/<name>.md` and skills in `.claude/skills/<name>/SKILL.md` are
thin adapters for the canonical `system/agents/` and `system/skills/` files (2026-11-12),
except older legacy skills that still hold their own text (checkin, news, imprint, learn,
legal-document-breakdown).

