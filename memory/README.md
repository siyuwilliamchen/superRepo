# Scoped working memory

Memory lets a worker resume a question and locate evidence. It does not record
William's learned states or grade him. It is not a transcript dump or a place for
hidden reasoning. Store concise decisions, observations, results, and next steps.

| Scope | Path | What belongs here |
|---|---|---|
| Shared, model-agnostic | `shared/` | Accepted cross-module decisions and entry links |
| Module | `modules/<module-id>/` | Current question, relevant decisions, unresolved issues |
| Agent-specific | `agents/<worker-id>/` | Owned work, partial results, interruptions, handoff |
| Tool-specific | `tools/<tool-id>/` | Observed host behavior and environment workarounds |
| Model-specific | `models/<registered-key>/` | Dated observations tied to an exact model and task |

Read shared and selected module state first. Add only your own handoff and the
applicable tool/model observations. Read another worker's handoff when taking
over or coordinating its actual task, not by default.

Every substantive memory entry identifies its scope, owner, update date, basis
(source or user decision), remaining uncertainty, and when to recheck it. Shared
facts point to canonical cards/evidence. Corrections append or supersede explicit
claims; they do not quietly erase the old reason for a decision.

Promotion path: worker observation -> supported proposal -> assigned integrator
checks it -> shared/module entry with evidence. Disagreement stays visible until
resolved. A repeated model answer is not independent evidence.

No profile overrides the active user request or project rules. Model memory is
especially provisional: retest on version changes. A directory name provides
organisation, not privacy; all tracked memory is readable by repository readers.
Keep credentials, raw audio, private scratch, and local session databases out of
tracked memory. Local runtime state is in `.local/`.

Use [handoff fields](templates/handoff.md) and
[model observation fields](templates/model-observation.md) when needed. Create
per-agent/per-model directories only for real work; do not prefill invented memory.
