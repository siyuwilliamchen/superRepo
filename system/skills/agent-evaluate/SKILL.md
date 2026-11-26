---
name: agent-evaluate
description: Evaluate an AI worker's actual use of SiyuOS rules, scoped memory, skills and evidence from its task, tool trace and outputs; distinguish process visibility from demonstrated behavior.
---

Read `system/methods/agent-evaluation.md` and the applicable project/module rules.
Review the original task and artifacts before the worker's self-assessment. Obtain
the real tool trace or receipt run; no trace means process use is unverified.

Run `python tools/agent_run.py audit --run RUN_ID` when local receipts exist, then
inspect the output and source passages yourself. A mechanically clean run is only
ready for review. Apply the rubric with concrete evidence, not headings, read
counts or the worker's claim that it followed the system. Distinguish inability
to observe a step from evidence that the worker skipped it.

Write a scoped review under `catalog/evaluations/`, identifying reviewer
independence, source versions, failures, unknowns and the smallest repair/retest.
Do not rewrite evidence to make a result pass, auto-promote worker claims to shared
memory, or grade William. Behavioral trials use isolated fixtures and blind task
prompts, not injected fake facts in the live vault. Delegation requires actual
session authorization; this workflow alone does not grant it.
