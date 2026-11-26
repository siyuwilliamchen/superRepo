# Publication: from the frozen brief to a rebuildable edition

Phase 4 of "LiveOS research through conversation" (William's design, 2026-11-25, Draft 1, filed
at `Project_Management/inputs/William_2026-11-25_LiveOS_Research_Conversation_Spec.md`, sections
3 "Writer", 4 "Good enough, write it", 6 and 8). Built 2026-11-26 on top of the Coordinator
(`system/methods/coordinator.md`) and the Conversationalist's frozen brief
(`system/methods/conversationalist.md`). Code: `tools/publish.py`. Tests:
`tools/tests/test_publish.py` (4 tests). Writer role: `system/agents/report-writer.md`, section
"Receiving a frozen brief". Package layout: `reports/README.md`.

## The rule

Publication starts on William's explicit word and nowhere else. The only thing that can open a
report package is a frozen brief that names its authorising turn **and** the write ticket the
Coordinator issued for that brief. Everything from the package to the delivered HTML and PDF is a
deterministic build: no model, no clock, no network. A later result cannot change a published
edition; it can only propose a revision, which William accepts or not.

## The path

| Step | Who | Command | What exists afterwards |
|---|---|---|---|
| 1. "Good enough, write it" | Conversationalist | `python tools/conversationalist.py brief --session S --turn u-N [--accept-limitation]` | `sessions/S/briefs/brief-N.json` and a `write` ticket in the ledger |
| 2. Open the package | Writer | `python tools/publish.py scaffold --brief sessions/S/briefs/brief-N.json --ticket T-00NN` | `reports/<report-id>/` with the brief copied, `publication.md`, `data/`, `figures/`, `evidence/`, `manifest.json` |
| 3. Write | Writer (the model) | edits `publication.md`, `data/*.csv`, `figures/*.json` | the publication sources |
| 4. Refreeze | Writer | `python tools/publish.py freeze --report <id>` | `manifest.json` lists every input with its sha256 again |
| 5. Build | Writer | `python tools/publish.py build --report <id> [--edition v1]` | `output/reports/<id>/<edition>/index.html`, `report.css`, `index.pdf` (when the renderer is present), `build.json`; `reports/<id>/editions.json` records the edition |
| 6. Prove it rebuilds | Writer, evaluator | `python tools/publish.py verify --report <id> [--edition v1]` | a second build compared byte for byte; a missing input named precisely |
| 7. Close the ticket | Writer | `python tools/coordinator.py complete T-00NN --attempt-id … --artifact reports/<id>/` | the result reaches the session inbox |
| 8. A later result lands | anyone | `python tools/publish.py revise --report <id> --result <ticket or sessions/S/inbox.jsonl:n>` | `reports/<id>/revisions/proposal-N.{json,md}`; the edition and the sources untouched |

Step 2 is refused, and nothing is written, when: the brief has no `authorized_by_turn`; that
turn is not in `sessions/S/turns/`; the ticket is not in `workflow/outbox/write/`; the ticket is
not a `write` ticket; its `request_key` is not `S/u-N/brief-N` (the key the Conversationalist
files); or the ticket is canceled or superseded. This is the gate in section 8, phase 4: work
completed before approval produces zero publication drafts. `tools/tests/test_publish.py`
runs the whole chain with the real `conversationalist.py` and `coordinator.py` commands against a
scratch root and checks every refusal.

## What the package holds (section 6, "Source retained")

| Spec row | In the package | Notes |
|---|---|---|
| Markdown with stable section and claim references | `publication.md` | Every heading carries an id (`{#sec-question}`, `{#sec-O-1}`, `{#claim-C-07}`); the claims appear in William's order, each with the qualification that stays attached, the open ticket that could change it, and the revision that already touched it; then the deliberate omissions, outstanding disagreements, limitations, and the evidence revisions |
| Small CSV | `data/claims.csv`, `omissions.csv`, `disagreements.csv`, `limitations.csv`, `revisions.csv` | written in the brief's order, read in file order; rendered as tables by reference (`![caption](data/claims.csv)`) |
| Declarative figure definition | `figures/claim-map.json` | the claims as the brief relates them, drawn as a deterministic grid (one row per outline entry, open and returned tickets below, edges "could change" / "revised"); no layout seed |
| Essential original document | `evidence/<ticket>.json` | the ledger record of every result the brief incorporated, with its parents (the research behind an interpretation), so source references survive even if the ledger is pruned |
| Build manifest and pinned environment | `manifest.json` | every input with sha256 and size; renderer name and version; theme hash; declared font stack; locale; timezone (UTC); data ordering; "no seeds"; "no clock" |
| The authorisation | `brief.json`, `ticket.json` | byte copies of the frozen brief and the write ticket; `freeze` refuses if either differs from its original |

Not inputs: `manifest.json` itself, `editions.json` (what was built, where, with which hashes),
`revisions/` (proposals). `output/` is outside git (`.gitignore` already lists it).

## Build and delivery (section 6, "Build and delivery")

Resolve and verify inputs → validate references → generate tables and figures → render HTML and
print PDF from the same content → check → publish outside git. In code:

1. `build` refuses, naming the file, if any manifest input is missing (`immutable input missing:
   reports/<id>/data/claims.csv (sha256 …, N bytes, listed in reports/<id>/manifest.json)`, exit 3),
   changed (exit 4) or unlisted.
2. The Markdown subset renderer (standard library) resolves every `![…](data/x.csv)` and
   `![…](figures/x.json)`; a missing file becomes a named failure, not a blank.
3. Every internal `#anchor` must exist on the page; the build record lists the sections.
4. PDF: the renderer the vault already uses, Python Playwright driving the installed Chrome
   (`tools/build_platform_pilot.py`, `modules/platforms/README.md`), with locale and timezone
   pinned on the browser context, A4, CSS page size, backgrounds on. The build record names the
   Chromium and Playwright versions and the OS. When the package or Chrome is absent, `build`
   says exactly which (`pdf.missing`) and produces HTML only; it installs nothing.
5. With Chrome present the build also records page errors and desktop overflow. Phone-width
   overflow was checked once by hand with `node tools/page_render.cjs` (clean at 1100 light,
   1100 dark, 390 light); that check is not part of `build`.

## Determinism: what is and is not shown

| Claim | Status | Evidence |
|---|---|---|
| Two builds of the same package give byte-identical `index.html`, `report.css`, `build.json` | verified | `test_approved_brief_builds_package_and_edition_and_rebuilds_byte_identical`; `verify` on the manual run |
| Two builds give the same PDF after normalising `/CreationDate`, `/ModDate`, `/ID` | verified on this machine | same test and run; in practice Chrome's output was identical before normalisation too |
| A fresh machine reproduces the PDF | not shown | glyph shapes follow the installed fonts; no font file is shipped. The manifest says so. Byte identity across machines would need shipped fonts and the same Chromium |
| No clock in the generation path | verified by reading | `publish.py` never calls a clock; dates shown are inputs (brief and ticket timestamps) |
| No live URL in the generation path | verified by reading | the renderer opens only `file:` URIs; nothing is fetched |

## Revision proposals (section 3, "A later material result")

`revise` takes a finished ticket or an inbox item, works out which brief claims it changes and
which sections and anchors those map to, whether it closes a limitation the brief carried, and
writes `revisions/proposal-N.json` and `.md` naming the published edition by name, path and HTML
hash. It asserts afterwards that no publication source changed. A result that touches no claim in
the brief still gets a proposal marked not material, for the record. The new edition, if William
wants it, is an ordinary `freeze` and `build` after he says so; the old edition's record stays in
`editions.json`.

## Where this departs from the design

- **No reviewer passes are wired in.** The spec's Writer subsystem (technical, reader,
  plain-format reviewers, one editor) exists as the revision fleet (`system/methods/revision-fleet.md`)
  and still runs by hand on the built edition. The build does the mechanical checks only.
- **One Markdown, one locale per package.** The vault's pages are Chinese with an English twin;
  a brief carries no language. `scaffold --locale` sets the `lang` attribute and the browser
  locale; a twin is a second package or a later feature.
- **The theme lives in `tools/publish.py`** (`THEME_CSS`, hashed into the manifest) rather than
  in a shared file, so a layout-only change is a renderer version bump and a rebuild. This is
  the simplest way to keep "a layout-only edit to the shared theme can rebuild any supported
  edition" true without a second owned path.
- **Pagination is not compared.** `verify` compares bytes; with identical bytes pagination is
  identical, but no page count or break positions are extracted. If a future renderer makes the
  PDF non-deterministic, a page-level comparison would be needed.
- **No Parquet, no external object store.** Everything in a brief-derived package is small
  CSV and JSON. The housekeeping rule for oversized originals (`library/objects/`, hash
  pointers) is unchanged and would apply if a package ever needed one.
- **The roster is not changed.** `report-writer` already advertised `write` with
  `reports/**` in its write scope; `tools/publish.py` could be named in its roster entry as the
  Conversationalist's entry names its tool. Proposed line for `workflow/roster.json`, role
  `report-writer`: `"tool": "tools/publish.py"`.

## Approvals and follow-ups for William

1. **Adopting the worktree.** Built in `.claude/worktrees/conversationalist`, nothing committed.
2. **First real package.** None exists; the only runs are scratch roots in tests and one manual
   run under `%TEMP%`. The first real brief should be a short topic so the Writer's editing loop
   (scaffold → write → freeze → build → verify) is seen once end to end.
3. **`system/methods/README.md` row** (not edited here): `| Publish an approved brief |
   [Publication](publication.md) | Package of sources, deterministic HTML/PDF edition outside git,
   byte-for-byte verify, revision proposals |`.
4. **Fonts.** If byte-identical PDFs across machines matter, choose a font to ship and pin it.
