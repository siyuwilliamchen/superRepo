---
name: liveos-context
description: Find scoped context and maintain a resumable handoff in the SiyuOS vault when starting, resuming, or transferring a research or maintenance task.
---

# LiveOS context and handoff

Use the repository root as the working directory. Read `system/README.md` and
`memory/README.md`, then select the module in `modules/registry.json`.

Run `python tools/liveos.py context --module <module-id> --tool <tool-id>` to get
the starting paths. Add `--agent <worker-id>` and `--model <registered-model-key>`
when applicable. This prints a reading list; it does not read or validate the
substance of the documents for you.

Select the applicable workflow from `system/methods/README.md`. For substantive
vault work, retain the actual host tool trace or start a run with
`tools/agent_run.py`; see `tools/agent-runs.md`. A reading list is not a read log,
and a read log is not proof that the answer applied the context. Never backfill
unobserved reads or describe self-review as independent evaluation.

Read applicable rules, shared/module state, and the relevant key card. Inspect
its supporting material before making a load-bearing claim. If the card is stale
or incomplete, search the relevant module and record the gap. An empty card index
does not establish that the vault lacks evidence.

For repeated searches, `python tools/liveos.py index --module <module-id>` updates
the local Markdown search cache. `search --module <module-id> <query>` reads it.
Search results are leads. The tool reports whether a cached hit has changed; open
the current file. It excludes original-document bodies and generated pages.

Write your task outcome and next dependency to
`memory/agents/<worker-id>/current.md`. Include source revisions, inspected paths,
changes, tests actually run, remaining uncertainty, and ownership. Use
`memory/templates/handoff.md` as a field guide, not a mandatory prose layout.

Promote only supported, task-relevant conclusions into shared/module memory and
key cards within your assigned integration scope. Do not copy private scratch
notes, model-specific habits, or unsupported summaries into shared fact.

Respect `system/coordination.md`. This workflow does not authorize commits,
external writes, bulk deletion, or spawning other agents.
