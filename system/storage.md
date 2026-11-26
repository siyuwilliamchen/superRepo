# Storage contract

Track authored Markdown, source records, diagram definitions, templates, styles,
code, and small assets needed to reproduce the reading views. Storage format does
not determine the quality or truth of the content.

New local-only areas have their own ignore files:

- `library/`: originals, with a separate backup and stable source records.
- `output/`: reproducible HTML/PDF and build outputs.
- `.local/`: disposable search caches and local runtime state.

Existing `sources/`, `inputs/`, `pages/`, `reports/`, and graphs remain unchanged.
Do not blanket-ignore all PDFs or HTML: some are originals or the only authored
version. Ignoring a path does not remove it from Git history or stop tracking it.

Before a later migration:

1. Inventory the exact paths, references, sizes, and content fingerprints.
2. Assign each original a stable ID and a verified retrieval/backup location.
3. Prove local reading outputs can be rebuilt from tracked inputs, with figures
   and source links intact. Existing custom pages need this proof individually.
4. Propose a specific move/removal list and repair references. Preserve immutable
   evidence paths unless William authorizes that migration.
5. Verify restoration before retiring any unique copy. Treat Git object cleanup
   separately from deletion of working files, and coordinate with its owner.

A GitHub-only reader can inspect tracked extracts and notes. It cannot inspect an
ignored original unless a source-provider connection supplies it. State that
boundary in answers and source records. A future connector must check the source
fingerprint; a URL alone does not pin a document's contents.

The platform pilot now has a Markdown renderer; its two index pages preserve the
saved November 2 content and figures. Other pages still require their own rebuild
proof. See `modules/platforms/README.md` and `catalog/audits/2026-11-08/`.

The original-library importer makes verified regular copies outside this repo,
then restores them into ignored `library/objects/`. A content hash identifies each
object; the source catalogue preserves all former paths as aliases. Legacy files
remain in place for compatibility and may still be tracked. This does not reduce
the working tree or Git history yet. The current outside-repo copy is on C:, so
an off-device copy is still needed before retiring legacy copies.
