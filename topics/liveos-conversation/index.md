# Topic: LiveOS research through conversation (the system itself)

Navigational entry point for work on the conversation system: the Coordinator, the
Conversationalist, the Interpreter and the Writer handoff. A worker starts here and follows
exact references before any wider search.

- **Topic id:** `liveos-conversation`
- **Aliases:** LiveOS conversation spec, conversationalist, coordinator, return relay, voice relay
- **Domain:** system design (no interpreter profile; this topic is about the vault's own machinery)
- **Status:** opened 2026-11-26 as the session topic for development assignments on the design.

## Governing question

How does William talk with a partner that has already studied a question, challenge it, commission
more work while talking, receive the dated result later, and hand the agreed argument to a writer,
with every durable part surviving a restart, a provider switch or a dead device?

## Canonical sources

| Evidence | Where | Use |
|---|---|---|
| The design, Draft 1 (William, 2026-11-25) | `Project_Management/inputs/William_2026-11-25_LiveOS_Research_Conversation_Spec.md` | Roles, routes, ticket contract, timing, failure rules, acceptance cases |
| The ledger and Housekeeper handoff (William, 2026-11-25) | `C:/Users/emuwi/Downloads/LiveOS_Vault_Ledger_Update_Prompt.md`; survey and proposal in `Project_Management/agent-system/ledger-pilot-proposal.md` | Artifact ledger; a separate pilot, owned by its own session |
| Coordinator: what was built | `system/methods/coordinator.md`, `tools/coordinator.py`, `tools/tests/test_coordinator.py` | Phase 1: tickets, receipts, leases, exactly-once follow-on, delivery, stall guard |
| Conversationalist: what was built | `system/methods/conversationalist.md`, `tools/conversationalist.py`, `tools/tests/test_conversationalist.py` | Phases 2–3: durable turns, outline, corrections, acknowledgment levels, catch-up, relay, checkpoint, brief |
| Role definitions | `system/agents/conversationalist.md`, `workflow/roster.json` | Canonical role text; roster with client declarations |
| The earlier voice starter | `Project_Management/inputs/2026-11-06_LiveOS_Codex_Starter/LIVEOS_SPEC.md` | Superseded by the 2026-11-25 design where they differ |

## Current claim map

None. This topic has no Interpreter; decisions are William's and recorded in the method docs.

## Known gaps

- The Interpreter and its claim maps (phase 3 of the design) are not built.
- Spoken playback to a listener is unverified on every host; synthesis to a file is verified.
- Event delivery into a Codex chat was reported once by William (2026-11-26) and not reproduced here.
- The ledger is not committed automatically; a `remote` acknowledgment needs a remote and a commit, both William's decisions.

## Related topics

- `topics/borrowing-consent/index.md`: the seed topic the design's worked example uses.
