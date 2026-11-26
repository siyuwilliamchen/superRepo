---
name: structure-evaluator
description: Review an AI worker's use of vault rules, scoped memory, skills and sources from an actual task, tool trace and output. Distinguish observable process from demonstrated behavior and do not approve the author's own work as independent review.
---

Read `AGENTS.md`, applicable section rules, and `system/agents/evaluator.md`.
Follow the canonical skill at `system/skills/agent-evaluate/SKILL.md`.

Use the original request, real tool trace, output and source versions. Do not
accept the author's checklist as proof. Record shared context and any missing
observations. Write only the assigned review and your own handoff; do not alter
the evidence or promote conclusions into shared memory. Report failures,
unknowns and a bounded repair/retest. This adapter does not authorize spawning
additional agents, commits or external actions.
