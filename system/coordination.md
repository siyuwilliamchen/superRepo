# Concurrent work and handoff

Before writing, identify your agent ID, tool, role, known model key, task, and
owned paths. Use `memory/agents/<agent-id>/current.md` for your handoff. This is
an ownership convention, not a filesystem lock or permission grant.

- One writer owns each shared file for a task. Work on separate paths when
  another worker is active. Use available handoffs and path ownership to resolve
  overlaps; continue independent authorized work without repeated status prompts.
- Research workers write their assigned findings; the integration owner updates
  the shared card or decision after checking the source. Do not silently turn a
  worker's hypothesis into shared fact.
- Read a file immediately before editing it. If another worker changed it,
  preserve their changes and reconcile only the overlapping portion.
- Record the source revision, files changed, checks actually run, unresolved
  issues, and next dependency in the handoff. Record outcomes, not hidden reasoning.
- Keep Git housekeeping separate from content work. Do not remove lock files,
  stop another worker, rewrite history, run cleanup, or stage broadly while a
  pack/migration writer is active.
- A process disappearing is not enough to prove an external agent's task is
  finished. For dependent work, use its completion report, an agreed handoff, or
  available repository evidence; then recheck paths, repository state, and rules.
  Do not require that signal for separate paths whose work does not depend on
  the packing result. Do not infer completion merely to remove a dependency.
- Follow current host and task limits on delegation. The existence of agent
  role files does not request or authorize spawning additional agents.

An interrupted worker's handoff stays available. Its age does not automatically
transfer ownership. A coordinator can explicitly reassign work and record why.
