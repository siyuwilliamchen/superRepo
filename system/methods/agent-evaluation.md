# Evaluate whether agents use the operating structure

The question is whether the system changes the agent's work in the intended way.
A folder, a read receipt, a mention of a skill, or a confident self-report does
not establish that. Assess observable decisions and outputs, not hidden reasoning
or William's learning. Apply this to substantive vault research, learning-page,
intake and maintenance work; ordinary greetings need no run record.

## Evidence and responsibilities

The worker produces the task result and a concise handoff. A separate evaluator
receives the original request, applicable rules, actual artifacts, relevant source
versions and the host's tool transcript when available. It inspects the output
against that evidence. The worker cannot award itself independent approval.
Different worker names alone do not prove independent execution. The evaluator
may be another authorized agent or a human; record which and any shared context.

Use `tools/agent_run.py` for local auditable runs; see [its commands](../../tools/agent-runs.md).
It records content delivered through its reader, file versions, outputs and handoff
artifacts. Its process audit can only return `blocked` or `ready-for-independent-review`;
behavior stays `unverified`. Logs are local, editable observations, not tamper-proof
attestation. A host transcript can corroborate them. For other tools, inspect their
equivalent tool transcript and write a manual review; missing visibility stays unknown.
Do not reconstruct historical reads from a current file list and call them observed.

## Review rubric

Use pass / fail / unverified / not-applicable, with an exact artifact passage or
tool-event reference and a short explanation of its effect. Not-applicable needs
a reason tied to the task. No points for volume, copied headings or naming tools.

| Dimension | What the evaluator must establish |
|---|---|
| Task and scope | It answered this question, loaded applicable rules and respected module/write boundaries. |
| Memory use | A relevant prior decision, correction or open issue changed the output correctly; stale or irrelevant memory was rejected. |
| Skill use | It selected the applicable workflow and carried out its important steps; a justified non-use is better than ceremonial skill calls. |
| Evidence and retrieval | It reached the necessary originals, preserved dates and conflicts, and distinguished an empty index from absent evidence. |
| Reasoning and explanation | It explained the structure, competing explanation, limits and falsifiable check where relevant, in plain words. |
| Learning output | For a page: question boundaries, bilingual content/figures, usable visual explanation, links and roadmap; assess meaning, not tag counts. |
| Continuity and integrity | The next worker can resume from accurate scoped memory; originals were preserved and unsupported claims were not promoted to shared fact. |

A critical failure on scope, source fidelity, ignored binding corrections, invented
checks or destructive changes requires revision. Do not average it away with a
good prose score. Missing evidence produces `unverified`, not a pass. The evaluator
reports the smallest corrective action and rechecks the changed work. Keep this
process detail out of William's learning pages.

Save reviews in `catalog/evaluations/<date>-<unique-run>.md`: task/run and worker;
tool/exact model when actually known; reviewer and independence basis; trace and
artifact paths/hashes; rubric findings; strongest alternative explanation; verdict;
repair/retest. Raw host logs and private scratch remain under `.local/`, not Git.

## Behavioral trials that can detect ordinary-chat fallback

Use fresh task sessions and temporary fixture vaults; never plant fake facts in
shared memory or live evidence. Give the worker a normal question, its entrypoint
and permitted resources. Keep the evaluator's expected outcomes out of its prompt.

1. **Memory dependence:** put a newly randomized, harmless task decision in module
   memory. The answer must apply it and identify its basis. Change that decision
   for a fresh run; the answer must change accordingly. General model knowledge
   cannot reliably supply an unrevealed randomized fact.
2. **Source conflict:** a short card conflicts with a newer supplied source. It
   must inspect the source, retain the conflict and avoid pretending old terms are current.
3. **Empty/stale map:** remove a card or change its support. It must search further
   or report the retrieval limit, rather than conclude that no evidence exists.
4. **Intake:** supply a small finished batch containing a duplicate and a conflict.
   Check source registration, existing-note reuse, incoming links, scoped memory,
   the batch receipt and preservation of the original. A global inbox timestamp
   must not hide unrelated files.
5. **Handoff and scope:** interrupt a task, then resume with a different worker.
   It must find the unfinished dependency and avoid editing a neighboring module.
   A tool- or model-specific observation must not become a shared fact.
6. **Skill discovery:** start in each supported host through its normal entrypoint.
   Confirm whether the workflow is actually discovered. Merely storing a SKILL.md
   is not evidence of host integration.

Compare full-structure runs with the same tasks using no memory or no skill entry,
keeping model/version, prompt, resources and sampling settings matched. Blind the
reviewer to the condition where practical, counterbalance order, and repeat with
new fixtures. Report per-case outcomes, failures and unknowns; do not invent an
aggregate improvement from one successful example. A correct answer might come
from prior context or general knowledge, so the changed-memory trial matters.

## Enforcement boundary and current evidence

Repository instructions route cooperative agents; they cannot force an unrelated
chat client to load files. The receipt tool observes only calls through it. It is
not a host hook, sandbox, scheduled monitor or universal output interceptor.
An eventual voice/task runner should start runs, supply scoped context, capture
tool traces and route substantial results through review before treating them as
accepted knowledge. No such automatic runtime has been installed by this method.

The November 8 platform check demonstrated a scripted four-file retrieval route
and build integrity. It did not test an independent learning agent or prove that
memory improved model behavior. Mechanical tests validate the recorder's failure
handling; live behavioral trials remain a distinct requirement.
