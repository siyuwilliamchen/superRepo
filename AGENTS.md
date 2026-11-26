# AGENTS.md: how any agent works in this repository

This file is read by Codex and by every other host; Claude Code also reads `CLAUDE.md`, which
points here. The canonical rules of the operating structure are in `system/README.md`; the
canonical role texts are `system/agents/<name>.md`, and the host adapters under `.claude/agents/`,
`.codex/agents/` and `.agents/skills/` only point back to them. Edit the canonical file, never an
adapter's instructions.

## Ownership (set by William, 2026-11-26)

- **Claude Code is the implementation owner.** It builds and changes the tools, roles and methods.
- **Codex coordinates and verifies.** It runs the checks below, reads the ledger and the handoffs,
  and reports gaps; it does not rewrite the implementation to make a check pass.
- **One user-facing Conversationalist decides and dispatches.** No other role talks to William or
  files requests on its own account; workers return results through the Coordinator.
- **The Coordinator is a durable routing and recovery service**, ordinary code, the only writer of
  `workflow/`. **The watchdog stays independent** of the Coordinator and of any conversation.
- Nothing here enables a machine-wide service (scheduled task, hook in a user settings file) or
  publishes anywhere; both wait for William's explicit word each time.
- Domain content and private session data do not enter this repository. `sessions/` is ignored;
  claim maps, inventories, research and pages live in the vault that owns them.

## Verification checklist (Codex)

1. `python -m unittest discover -s tools/tests -p "test_*.py" -v` from the repository root: 70 tests
   on 2026-11-26. The ledger baseline test skips when the vault's IPO-timing chain is not present.
2. `python tools/coordinator.py status`: every ticket in `workflow/outbox/` has a lifecycle in
   `workflow/events/`; a completed ticket is delivered or has a follow-on child.
3. Each handoff in `memory/agents/*/current.md` names files that exist here, and the checks it
   claims match the test output.
4. `git status --porcelain`: no `sessions/`, `.local/`, `output/` or domain path is tracked.
5. For an adopted change from a vault worktree: the diff against that worktree is limited to path
   adaptation, and the tests still pass in both places.

## Unresolved integration gaps (2026-11-26)

1. **Vault root: resolved on 2026-11-26, one choice left.** Domain repositories are registered in
   `config/vaults.json` and resolved by `tools/vaults.py` (root first, then each vault); role texts
   write vault paths as `<vault>/...`; the Coordinator's scope check and the Conversationalist's
   topic lookup use it; a clean checkout runs its tests with no vault present. Still open: the
   methods and skills adopted from the vault cite vault-relative files (`Project_Management/...`,
   `<Field>/...`) in prose without the `<vault>/` prefix; the notation in `system/README.md`
   covers them, a line-by-line pass has not been made.
2. **Two copies of the Coordinator.** The vault's main checkout holds untracked `tools/coordinator.py`,
   `workflow/`, `topics/` from 2026-11-25; the worktree copy adopted here adds the `build` ticket kind
   and roster roles. Reconcile the vault copy to this one, or point the vault at this repository.
3. **The vault's main-checkout ticket T-0001** (`liveos-conversationalist-return-relay`) is still
   queued there; this repository's T-0002 did its work.
4. **Receipts of the ledger pilot** live in `ledger/receipts/`, not in the Coordinator's events; a
   `--artifacts` flag on `coordinator.py complete` would join the two ledgers (proposed, not built).
5. **Hooks and services need William:** `.claude/hooks/session_runs.py` is here but not registered
   in any settings file; `tools/register_watchdog_task.ps1` is written but not run; relays die with
   the session that started them.
6. **Writing agents do not yet call the ledger write path**; one line per canonical role text is
   proposed in `memory/agents/claude-code-ledger-pilot/current.md`.
7. **Unverified behaviour:** delivery into a Codex chat (reported once by William, not reproduced),
   spoken playback to a listener, PDF byte identity across machines, the deadline numbers in
   `workflow/deadlines.json`.
8. **`tools/vault_trim.py`** here is the vault's committed version; the vault's main checkout has
   newer uncommitted edits (the `detach` command) owned by the ledger-pilot session.
