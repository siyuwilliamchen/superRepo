# Codex adapter

Read root `AGENTS.md`, then `system/README.md`. Apply any nearer `AGENTS.md` to the
paths you edit. Use the tools available in the current session; do not assume a
connector, model, or delegation feature exists because another session used it.

Record the tool as `codex`. Record the exact model only if the host exposes it.
Load shared/module memory, your own worker handoff, and the matching model
observations if relevant. Do not load every other worker's private scratch state.

Canonical project skills live under `system/skills/` and agent definitions under
`system/agents/`. Codex discovery adapters (2026-11-12): custom agents in
`.codex/agents/<name>.toml` (project scope; required `name`, `description`,
`developer_instructions`) and skills in `.agents/skills/<name>/SKILL.md` (Codex scans
`.agents/skills` from the working directory up to the repository root). Each adapter
only points to the canonical file. Custom agents inherit the parent session's sandbox
and approvals, so an instruction not to edit is a rule, not a separate read-only sandbox.
If a custom agent cannot be invoked by name, spawn a generic worker told to read
`system/agents/<name>.md` first. Discovery in a fresh Codex session is not yet verified.
