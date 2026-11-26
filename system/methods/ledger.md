# The artifact ledger and the Housekeeper

Pilot built 2026-11-26 under ticket T-0006, from William's handoff "LiveOS vault ledger and
Housekeeper" (sections 2 to 7) and the decisions in
`Project_Management/agent-system/ledger-pilot-proposal.md` section 8. Code: `tools/ledger.py`.
Tests: `tools/tests/test_ledger.py` (the seven exercises of handoff section 7, the protected
roots, and a read-only baseline on the real IPO-timing chain). Record format: `ledger/README.md`.

## What it is for

William says "remove the superseded drafts on this topic and keep the evidence behind my
published reports". The Housekeeper must answer from metadata: which files exactly, which ones
are held and by what, which ones nobody can vouch for yet. Another agent asks "where is our
evidence about investor consent thresholds" and finds it across folders. Neither question may
depend on a model reading every document.

Four things stay separate and are joined by stable ids:

| Thing | Where | Owner |
|---|---|---|
| Roster: who may do what | `workflow/roster.json` | Coordinator; the ledger enforces its write scopes |
| Ticket ledger: what was asked, what happened | `workflow/outbox`, `workflow/events` | `tools/coordinator.py` |
| **Artifact ledger: what durable material exists, why, where, what requires it** | `ledger/<domain>/artifacts-<xx>.jsonl`, `ledger/receipts/`, `ledger/holds/`, `ledger/plans/` | `tools/ledger.py` |
| Library registry: original documents by content hash | `catalog/sources/library.jsonl` | `tools/vault_trim.py` (unchanged) |

Originals are not registered twice: an artifact's input may name a library object as
`sha256-<hash>`. Everything authored or derived (findings, interpretations, report sources,
datasets, figures, build code, disposable derivatives) gets an `A-` id that never changes.

## The write path: registration is part of the write

A worker stages a **batch** under one **operation key** with its ticket, attempt id and role,
then `python tools/ledger.py batch --file batch.json`. Single operations have flag forms
(`create`, `modify`, `move`, `retire`, `restore`, `register`). Order of events, always the same:

1. **Stage.** Intent is written to `.local/ledger/pending/<key>.json` with deterministic ids
   (`A-` + hash of key and position) and the digest of every staged source file.
2. **Check, in code, before any byte moves.** Protected roots (`inputs/` at any depth, the
   frozen October platform page `Economics/pages/platforms/index.html`, `.git/`, `library/`,
   the ledger's own records). The role's write scope from the roster. For modify, move and
   retire: `expected_version` must equal the record's version, and the record must not be
   retired. The bytes on disk must match the record (otherwise it is drift; see below). A path
   already owned by another artifact refuses a create or move onto it.
3. **Place bytes as a new file.** `modify` and `create` copy the staged source to a temporary
   file in the target folder and `os.replace` it onto the path. The old inode is never opened
   for writing, so a hard-linked sibling (a library object, a backup) keeps its bytes.
4. **Write records.** Version + 1; `changed` carries op key, ticket, attempt, role. A move
   across domains rewrites both domain files from the same operation; the id stays.
5. **Receipt.** `ledger/receipts/<key>.json`: the operations and their results. The same key
   applied again returns this receipt and changes nothing.
6. **Views.** The SQLite index and `ledger/<domain>/index.md` refresh. A failed refresh leaves
   the receipt marked `views: stale`; `recover` replays it.

What this guarantees, and the test that shows it:

| Guarantee | Test |
|---|---|
| One effect per operation key (retry after a lost acknowledgment) | `test_1` |
| Identity survives modify and a move across domains; both domain views update | `test_1` |
| A stale writer (old `expected_version`) cannot overwrite, and cannot resurrect a retired id; a new artifact at a reused path is not touched by an old receipt | `test_4`, `test_5` |
| Interrupt after staging: recovery discards the intent; after acceptance: recovery replays the views; paths, digests, reverse dependencies and receipts agree | `test_5` |
| Hard-linked sibling keeps its bytes through a modify and a retire; the recovery copy holds the edited bytes | `test_6` |
| Protected roots and out-of-scope roles are refused; a refused batch leaves no intent | `test_protected_roots…` |

Temporary files, `.local/`, previews that are not registered, and the ledger's own bookkeeping
need no ticket.

## Dependencies: three relations, one of which blocks deletion

- **Required input** (`inputs` on the record): what is needed to reproduce or substantiate
  the artifact. Declared by the worker when the artifact is created or modified; a digest may be
  pinned where an edition depends on exact bytes (`id@pin`). This is the only relation that
  holds an artifact against deletion.
- **Navigation link** (`links`): a page that merely points at something. Deleting the target
  dangles the link; the Housekeeper says so as a separate disposition and does not hold.
- **Claim relationship**: the Interpreter's map, not stored here.

The reverse lookup "who requires this input" is derived from the input lists, never stored. It
crosses domains and passes through intermediates: a report in `beta` that requires a figure that
requires a CSV in `alpha` holds the CSV (`test_2`). `required-by --id` prints every edge.

Each record carries `coverage`: `reconciled` means its consumers have been checked;
`unverified` means they have not. **An empty reverse lookup with unverified coverage is not
permission.** A legacy page that quotes a dataset without a manifest keeps that dataset
`unresolved`, with the cost of settling it (unregistered files under the domain roots) in the
plan (`test_3`).

## Drift

`drift [--domain]` compares every active record with the disk and with git, opening the body
only when size matches (targeted verification). Three results:

| Result | Meaning | What happens |
|---|---|---|
| `drift` | record and disk disagree (missing, size or digest differs) | a `modify` of that artifact is refused until `register --reconcile` accepts the external edit as a new version with provenance "external edit accepted" |
| `uncommitted` | record and disk agree; git has not got the bytes (M or untracked) | reported; committing is a separate step, as in the Coordinator |
| `unregistered` | files under the domain roots with no record | counted with bytes; this is the reconciliation cost |

Every writer that bypasses the ledger (a human in VS Code, a shell redirect, a build script run
by hand, another host) is caught here at the next look, not blocked.

## The Housekeeper

```
python tools/ledger.py housekeep plan    --request "..." [--domain D] [--topic T] [--kind K] [--state S] [--expired] [--exclude GLOB]
python tools/ledger.py housekeep approve --plan P-xxxx --ids A-..,A-.. --by william
python tools/ledger.py housekeep apply   --plan P-xxxx --op-key K --ticket T [--attempt-id ...]
```

1. **Plan.** The request becomes a filter on indexed metadata. Every candidate gets one
   disposition from the authoritative records (not the index):
   - **eligible**: no consumer, no hold, no policy, bytes verified, coverage reconciled,
     purpose known;
   - **held**, naming the reason: a consumer (id, domain, path, and the intermediate it comes
     through), a job hold (`hold --id --job --ticket`), a policy (`retain`,
     `approved-edition`, protected root);
   - **unresolved**, never permission: coverage unverified, purpose unknown (inventoried only),
     drift, missing from disk, or shared storage (`st_nlink > 1`: determine which path the
     consumer actually requires).
   The plan is saved in `ledger/plans/` with the git revision and the measures. An empty index
   produces an empty plan with a warning; nothing can be approved from it.
2. **Approve.** Only eligible items; the approval binds id, version, digest and path.
3. **Apply.** Under the lock, each approved item is revalidated now: version, digest and path
   must equal the plan, and the disposition is recomputed with current consumers and holds. A
   changed item is reported as `changed: needs a fresh disposition`; a newly held item as
   `held`. Eligible items are retired through `tools/vault_trim.py archive` (zip, verify, delete),
   the zip member is hashed against the record, and the record becomes a tombstone: reason,
   approval, op key, last path, and the restore reference (zip, member, digest). The receipt
   reports removed paths, logical bytes, and physical bytes freed **only as measured** (size
   when the link count was 1, else 0). The same op key applied twice has one effect (`test_4`,
   `test_7`).
4. **Restore.** `restore --id A [--to path]` extracts from the zip, verifies the digest, and
   places the file as a new inode. A path now owned by another artifact is a conflict; `--to`
   resolves it. The restored record is a new version, state active, with `from_backup` provenance.

## Index

`.local/ledger/index.sqlite3`, disposable, after `tools/liveos.py`. Tables: artifacts, topics,
inputs, links, receipts, holds, shards, metadata (git revision and time). A normal write
reloads only the record shards whose bytes changed; `index --check` says whether it is current;
`index --rebuild` recreates it from the records alone. Queries (`find`, `show`, `requires`,
`required-by`, `housekeep plan`) read the index; acceptance and dispositions read the records.

## Measures

Every query prints `measures`: index queries, file bodies opened, bytes read, model calls
(always 0). Observed in the fixture: `find --topic` opens 0 bodies; a plan opens one body per
candidate (digest verification); apply opens two per retired item (before archiving and the zip
check). The mechanical inventory of the real IPO-timing chain (30 files) opened 9 bodies, all
build scripts, 139 KB: a one-time bootstrap. Repeated whole-vault content scans fail this gate.

## Migration: honest coverage

`inventory --domain D --roots P... [--infer-inputs] [--chain PATH] [--write]` is the cheap
bootstrap: git paths and file metadata; kind guessed from folder and extension; with
`--infer-inputs`, the data files and sibling modules a build script names become its inputs and
the pages and figures it names become its outputs, marked `basis: inferred-from-script`. Records
start as `inventoried, purpose unknown, coverage unverified`, so nothing inventoried this way
is eligible until a person enriches it. Dry run by default; `--chain` prints what one target
requires, transitively.

Baseline on the real vault (read-only, `test_baseline…`): `stay-private-law.html` requires
`build_page.py`, `page_charts.py` and three CSVs under `IPOAGE-DATA/data/`. Gaps the inventory
cannot close by itself: `build_page.py` reads `research/IPOAGE-HOLDERS/holders_at_ipo.csv`
outside the roots; `compute_ages.py` takes `IPO-age.xlsx` as an argument; the Ritter PDF and
spreadsheet are library originals whose registry is not in this worktree.

## For every writing role (the shared contract)

Any role that creates or modifies durable material calls the write path with its ticket, attempt
id and role, and declares the direct inputs of what it produces:

| Role | Declares |
|---|---|
| research-agent, law-boundary-research, legal-document-breakdown | sources (library `sha256-` ids or registered datasets) and purpose of each findings file |
| interpreter | evidence inputs of a claim map |
| report-writer, rev-editor | the build inputs of every page and figure (data, build code, pinned where an edition depends on exact bytes); the editor submits changed files under one revision ticket |
| conversationalist, coordinator | durable session segments, briefs and checkpoints within their own scopes |
| rev-technical, rev-reader, rev-plain-format | nothing on article content; a persisted review record uses their own scope |
| vault-cleanup (the Housekeeper) | owns retire and restore through plan, approve, apply |

Canonical agent definitions should each gain one line pointing here; adapters stay thin. This
pilot did not edit them (outside its owned paths); the proposed lines are in the handoff
`memory/agents/claude-code-ledger-pilot/current.md`.

## Where this departs from the handoff, and what is not built

- Receipts live in `ledger/receipts/`, not in the Coordinator's event stream: `coordinator.py`
  was not to be edited. The proposed join is an `artifacts` list on a completion event.
- Acceptance uses a lock file and atomic file replacement, as the Coordinator does; a git
  commit per batch is a separate step. The receipt records the revision it was accepted against.
- Topic directories (`topics/<t>/index.md`) do not yet get a generated block; the generated
  view is `ledger/<domain>/index.md`.
- Not built: production cleanup, `PostToolUse` edit logging (needs William's hooks block),
  history rewriting, semantic link discovery, a service.
