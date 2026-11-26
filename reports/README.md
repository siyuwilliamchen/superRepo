# reports/

Two kinds of thing live here.

- **Older question-and-answer notes** (the `.md` files at this level, 2026-11 and before):
  William's own writing, kept as they are.
- **Report packages** `reports/<report-id>/`, opened only by `python tools/publish.py scaffold`
  from a frozen writing brief and its write ticket (`system/methods/publication.md`). A package
  is the canonical source of one approved report. Its editions are generated into
  `output/reports/<report-id>/<edition>/`, which is outside git.

## One package

| Path | What it is | Build input? |
|---|---|---|
| `brief.json` | byte copy of `sessions/<S>/briefs/brief-N.json`, the frozen writing brief | yes, immutable |
| `ticket.json` | byte copy of the `write` ticket the brief filed | yes, immutable |
| `publication.md` | the narrative: headings with stable ids (`{#sec-…}`), the claims in William's order with their anchors (`{#claim-C-07}`), qualifications, omissions, disagreements, limitations, revisions, sources. The Writer edits this. | yes |
| `data/*.csv` | small tables worth reading in a diff, written in the brief's order; rendered where `publication.md` references them (`![caption](data/claims.csv)`) | yes |
| `figures/*.json` | declarative figure definitions rendered to inline SVG by a deterministic grid (`kind: claim-map`) | yes |
| `evidence/<ticket>.json` | the ledger record of every result the brief incorporated, with the research behind it and its source references | yes |
| `manifest.json` | every input with sha256 and size; renderer and version; theme hash; declared fonts; locale; timezone; "no clock, no seeds". Written by `scaffold`, rewritten by `freeze`. | no (it is the list) |
| `editions.json` | which editions were built, where, from which manifest, with which hashes | no |
| `revisions/proposal-N.{json,md}` | a later result's proposal against a named edition; the edition is not changed | no |

## Commands

```
python tools/publish.py scaffold --brief sessions/S-08/briefs/brief-1.json --ticket T-0004
python tools/publish.py freeze  --report S-08-brief-1        # after editing the sources
python tools/publish.py build   --report S-08-brief-1 --edition v1
python tools/publish.py verify  --report S-08-brief-1 --edition v1
python tools/publish.py revise  --report S-08-brief-1 --result T-0007
python tools/publish.py status
```

`scaffold` refuses without an authorising turn in the brief and the brief's own write ticket in
the ledger. `build` and `verify` refuse when a listed input is missing or changed, and name it.
`verify` rebuilds into a second directory and compares bytes (the PDF after normalising its
volatile metadata).

## What is never done here

- No hand-editing of anything under `output/`; it is rebuilt from the package.
- No edition is changed after a later result; `revise` writes a proposal beside the package.
- No original document is copied in; an original lives once in `library/objects/` and is
  referenced by id and hash.
