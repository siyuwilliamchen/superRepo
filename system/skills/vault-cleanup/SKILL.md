---
name: vault-cleanup
description: Clean up the SiyuOS vault - census, cleanup proposal, then apply the approved groups (keep only latest versions, one copy of every original by pointer, delete superseded research, keep GitHub to the bare minimum). Use when William says clean up, trim, tidy, dedupe, or prepare for GitHub, or for the routine fortnightly cleanup.
---

# Vault cleanup

1. Dispatch one `vault-cleanup` agent (definition: `system/agents/vault-cleanup.md`) in proposal mode. Do not run a second one while one is working.
2. Give William its 5-line summary and the path of `catalog/audits/<date>/cleanup-proposal.md`. Ask which groups to apply, in one short question.
3. Send his answer back to the same agent (apply mode), or run steps 5–6 of the definition yourself.
4. Report what was freed, what failed, and what is left, with the tool output. Do not commit or push unless he asks.
