# LiveOS agent operating structure

Start here to work on a vault without loading the whole vault. This structure serves every
tool, agent, and model. It does not implement the voice application.

## Where things live now (2026-11-26)

This repository (superRepo) is the agent layer: roles, adapters, methods, skills, the
Coordinator, the Conversationalist, the watchdog, the ledger pilot, the publication handoff,
their tests and the workflow ledger. A **vault** is a domain repository: field folders, topics,
claim maps, pages, research, its own rules (`CLAUDE.md`, `AGENTS.md`, `Project_Management/`),
module registry, key cards and library of originals. Vaults are explicit external inputs,
registered in [`config/vaults.json`](../config/vaults.json) with their local paths; nothing here
assumes one is present, and `python tools/vaults.py list` says which are.

**Notation.** In role texts, methods and skills, a path written as `<vault>/...` or given relative
without a prefix among a vault's files (`Project_Management/LifeOS Method.md`, `<Field>/pages/`,
`topics/<topic>/index.md`) is relative to the active vault. Paths under `system/`, `tools/`,
`workflow/` and `config/` are this repository's. A reference is resolved root-first, then vault by
vault, by `tools/vaults.py`; the Coordinator and the Conversationalist use the same resolution.

## Reading order

1. Read this repository's `AGENTS.md`, then [requirements](requirements.md); then the active
   vault's root `AGENTS.md` and the LifeOS method and standing preferences it points to.
2. Select a module in the vault's registry (`<vault>/modules/registry.json`). Read its local
   rules and roadmap when the task touches that field.
3. Read only the matching [tool adapter](adapters/README.md),
   [agent role](agents/roles.md), and [model profile](models/README.md).
4. Load shared and module memory, then your own agent memory and applicable
   model observations. [Memory rules](../memory/README.md) define their limits.
5. Find relevant key cards (`<vault>/catalog/README.md`), then open the evidence needed
   for the question. Missing cards mean search further, not that evidence is absent.
6. Select the applicable [method](methods/README.md). For substantive vault work,
   retain an actual tool trace or the vault's run receipts (`<vault>/tools/agent-runs.md`).
   Apply [agent evaluation](methods/agent-evaluation.md) before claiming that the
   operating structure was followed successfully. Missing observation remains
   unverified; a self-report or clean file check is not independent approval.

A scoped reading list without a full content scan comes from the vault's own router, when it has
one (`python <vault>/tools/liveos.py context --module economics --tool codex`); this repository
does not ship it.

[Architecture](architecture.md) explains the boundaries.
[Coordination](coordination.md) explains concurrent work.
[Storage](storage.md) distinguishes authored sources from disposable outputs.
[Skills](skills/README.md) lists reusable workflows without copying their bodies.

The structure adds a routing layer around a vault's existing field folders. It does not relocate
evidence, remove old pages, or automatically load these files into tools that have not been
connected to the entrypoint.
