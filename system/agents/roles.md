# Agent roles

A role is a responsibility, not a model or a tool. The active user request and
host permissions determine which actions are actually allowed.

| Role | Responsibility | Default write scope |
|---|---|---|
| Researcher | Inspect evidence, test competing explanations, propose findings | Assigned new research entries and own handoff |
| Integrator | Reconcile findings, preserve disagreements, update shared cards | Explicitly assigned cards, module state, decisions |
| Reviewer | Check support, scope, contradictions, and reproducibility | Review findings and own handoff |
| Structure-use evaluator | [Evaluate actual memory, skill and evidence use](evaluator.md) from traces and task results | Assigned evaluation records and own handoff |
| Maintainer | Maintain routing, indexes, builds, and storage conventions | Assigned system/tool files and own handoff |
| Reviser (revision fleet) | [Read an article for one purpose](../methods/revision-fleet.md): technical boundaries, blind reader, or plain language and links | Its own review file in the run folder |
| Editor (revision fleet) | Settle the reviewers' advice and apply it to the article | The article's content files, rebuilt pages, its roadmap row, `editor.md` |

One worker may hold several roles for an authorized task. Separate worker IDs are
required for concurrent instances. Ownership is recorded in a worker profile
under `system/agents/instances/` or its task handoff. Avoid a global registry that
every worker must rewrite whenever it starts.
