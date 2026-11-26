# Tool adapters

Adapters contain host-specific entry instructions, not copies of shared policy.
Choose [Codex](codex.md), [Claude Code](claude-code.md), or [generic](generic.md).
Add another adapter when its behavior requires different instructions.

The root `AGENTS.md` and `CLAUDE.md` point to the shared operating entrypoint.
Reading an adapter does not install a plugin, skill, or background service. Hosts that do not
discover repository instructions must be given `system/README.md` explicitly.
