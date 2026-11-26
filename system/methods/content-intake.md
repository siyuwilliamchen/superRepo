# Content intake and filing

Use this when William supplies material or authorizes filing completed work. A
question about filing is not permission to ingest the entire backlog. Work on an
explicit batch; keep active research and other workers' files outside it.

Read the [check-in procedure](<../../Project_Management/Check-in Procedure.md>)
and [vault conventions](<../../Project_Management/Vault Conventions.md>). They
define note types, source IDs, duplicate-name checks and graph links. The learning
architecture and LifeOS method override their superseded learning-state steps.

## The route

1. **Receive and route.** Record the batch, owner, module, source paths, content
   hashes and origin/date when known. Preserve supplied originals. Select the
   module's rules and roadmap; do not invent a new field because a folder is empty.
2. **Register evidence.** Link the local original and its source manifest. Use
   `tools/source_library.py resolve --path ... --verify` for already imported
   originals. For new originals, preserve the required field source copy and
   register it there; mark library import pending until it has a verified backup
   and library record. The dated bulk importer is not a watched upload service.
3. **File knowledge.** Search existing titles, aliases and notes before creating
   anything. Build or update the appropriate source/topic/entity notes and link
   them to their parent hub and related concepts. Keep findings tied to original
   evidence. Preserve conflicting claims and add a dated indexing flag; do not
   overwrite immutable research or silently promote a summary into a fact.
4. **Update retrieval.** Refresh relevant key cards after reviewing their support;
   never just replace a hash to clear a warning. Update module memory only for a
   real change in current state. Record 'no change' and why when appropriate.
   Refresh the selected module index with `python tools/liveos.py index --module ID`.
5. **Build reading material only when requested.** Filing is Level 1 work. A new
   learning question follows the separate page/roadmap method; filing alone does
   not authorize generating a whole course or recording what William has learned.
6. **Check and record.** Check source links, note names, parent/incoming links and
   the new notes' sections; run the existing vault checker when filing Foam notes.
   Also run `python tools/liveos.py check`. Keep pre-existing problems separate
   from new failures, and state the scope of any partial check. Save a dated
   receipt, the checks actually run and the worker handoff. An evaluator reviews
   whether the notes faithfully preserve the evidence, not merely whether links exist.

The receipt goes under `catalog/intake/<date>-<unique-batch>.md` and names:
question/scope; owner/module; every input and hash; source/backup status; notes
created/updated; hub links; conflicts; cards/memory/index changes or justified
no-change; commands/results; unresolved items; and status (pending, needs-revision,
or filed for that explicit batch). Link it from the appropriate journal entry.
Use [the template](../../catalog/intake/TEMPLATE.md) only for real batches.

## Existing commands and their limits

- `python Project_Management/tools/vault.py inbox` discovers candidates using
  the legacy index and its global last-check-in date; it is not a complete audit
  of every original or new library object. Prefer explicit task paths for a batch.
- `python Project_Management/tools/vault.py check` checks the indexed knowledge
  network. It does not judge source fidelity or reasoning quality.
- `reconcile --write` can touch many notes. Use it only if the batch owns that
  write scope; otherwise repair the assigned parent links directly.
- Do not call `inbox --mark` for a partial batch: the current implementation moves
  a global timestamp and can hide untouched older items from the default inbox.
  Use a batch receipt instead. A full-inbox mark requires accounting for every item.
- The current `vault.py build` still emits learned-state fields. Do not invoke it
  through this pipeline until its output is separated from the abolished learning
  machinery. Filing and scoped search can be completed without that graph build.
- Never call learned/probe/learning-check-in commands. No commit is implied.

Nothing here automatically moves old originals, rewrites Git history, or uploads
private material. 'Filed' means the named batch is connected and checked; it does
not mean all vault contents are organized or that an agent has understood them.
