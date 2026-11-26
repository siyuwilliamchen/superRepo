# LiveOS working state

Updated: 2026-11-08. Owner: codex-platform-pilot.

Question: how should multiple agents and models share this vault without reading
everything, overwriting one another, or mixing task state with evidence?

Accepted direction: shared requirements; distinct tool/role/worker/model
identities; scoped memory; module registry; key cards with source fingerprints;
local generated views and a separately backed-up original library.

Current state: the structure and retrieval tools are connected from root
`AGENTS.md`, `CLAUDE.md`, and README. William directed autonomous progress without
repeated prompts and authorized migration steps 1–4. Both supplied packages pass
integrity checks; live law work is newer than those snapshots. The dated audit
records differences without altering either version. Twelve behavior tests pass.

The migration adds an ignored document library through verified copying, source
IDs and aliases, platform memory/cards, and a bilingual Markdown reading pilot.
Existing evidence paths and pages remain unchanged. No deletion, Git housekeeping,
remote creation, voice implementation or quant integration has been performed.

Counter: a new routing layer could duplicate stale indexes. Keep small canonical
registries, update only changed Markdown in the search cache, and mark key cards
stale when supporting file fingerprints change.

Check: a fresh worker can request an Economics reading list without opening the
original library; a changed supporting file makes its key card need review.
Observed migration results belong in the
[worker handoff](../../agents/codex-platform-pilot/current.md) and
[dated audit](../../../catalog/audits/2026-11-08/README.md).

Open items: an off-device backup/provider before retiring legacy originals,
renderers for further pages/modules, and the future quant repository location.
The local rollback copy is on the same drive. The voice starter remains
[the supplied draft](../../../Project_Management/inputs/2026-11-06_LiveOS_Codex_Starter/LIVEOS_SPEC.md).

2026-11-08 methods update, owner codex-method-maintainer: the
[methods index](../../../system/methods/README.md) now connects intake and
agent evaluation. Twenty-two mechanical tests pass. Actual learning-agent
behavior and fresh host discovery remain unverified; no automatic runtime gate
is installed. The current platform gaps card has a changed roadmap support and
requires review. See [the method handoff](../../agents/codex-method-maintainer/current.md).
