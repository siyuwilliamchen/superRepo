# ledger/: the artifact ledger

One record per managed artifact (authored or derived material). Original documents are not
here: their ledger is `catalog/sources/library.jsonl`, keyed by content hash. Method:
`system/methods/ledger.md`. Tool: `tools/ledger.py`. Never edit these files by hand; the tool
rewrites a shard atomically and the lookup index in `.local/ledger/` follows.

## Layout

| Path | What |
|---|---|
| `<domain>/domain.json` | the domain's folder roots (used to count unregistered files), when it was inventoried, which consumer classes are reconciled |
| `<domain>/artifacts-<xx>.jsonl` | one JSON line per artifact; `<xx>` is the third and fourth character of the id |
| `<domain>/index.md` | generated navigation table between `<!-- ledger:generated -->` markers; authored text outside the markers is kept |
| `receipts/<op-key>.json` | one receipt per accepted batch: ticket, attempt, role, revision before, results |
| `holds/<job>.json` | a running job's pin on an input: id, ticket, time |
| `plans/P-<id>.json` | a Housekeeper plan: request, filter, every candidate with its disposition and reasons, the approval bound to ids and versions |

A domain is a folder of the ledger, not of the vault: `economics` may own an artifact stored
anywhere. A move across domains rewrites the record into the other domain's shard with the same id.

## Record

```json
{"id": "A-7ba40d851e", "domain": "alpha", "path": "alpha/research/D-1/data/series.csv", "locator": null,
 "digest": "sha256:…", "bytes": 32, "version": 1, "kind": "dataset", "topics": ["consent"],
 "purpose": "yearly values behind the consent report", "role": "research-agent", "ticket": "T-1",
 "inputs": [{"id": "A-…", "digest": "sha256:… or null"}, {"id": "sha256-…", "digest": null, "locator": "library"}],
 "links": ["A-…"], "state": "active", "policy": "default", "coverage": "reconciled", "expires": null,
 "created": {"at": "…", "op_key": "K1", "ticket": "T-1", "attempt_id": "T-1#a1", "role": "research-agent", "how": "create"},
 "changed": {"at": "…", "op_key": "K1", "ticket": "T-1", "attempt_id": "T-1#a1", "role": "research-agent", "how": "create"},
 "retired": null}
```

| Field | Values | Who sets it |
|---|---|---|
| `id` | `A-` + 10 hex, stable for life | the tool, from the op key and position |
| `path` / `locator` | vault-relative path, or an external locator for retained objects | the write path |
| `digest`, `bytes`, `version` | current content hash, size, and a counter that every accepted operation increments | the write path |
| `kind` | `original`, `findings`, `interpretation`, `report-source`, `dataset`, `figure`, `derivative`, `build-code`, `unknown` | the worker |
| `topics`, `purpose`, `role`, `ticket` | stable topic ids, one sentence that distinguishes this artifact, owning role, originating ticket | the worker |
| `inputs` | direct required inputs; `digest` pinned where an edition depends on exact bytes; a library original as `sha256-…` | the worker or the build's manifest |
| `links` | navigation only; never holds against deletion | the worker |
| `state` | `active`, `inventoried` (mechanically registered, purpose unknown), `retired` (tombstone) | the write path |
| `policy` | `default`, `retain`, `approved-edition`, `disposable` | the worker; cannot lift a repository protection |
| `coverage` | `reconciled`, `unverified` (consumers not checked: an empty reverse lookup is not permission) | the worker or a reconcile |
| `expires` | ISO date for disposable derivatives | the worker |
| `retired` | `{at, reason, approval, op_key, path, restore: {backend, zip, member, digest, verified, physical_bytes_freed, nlink_before}}` | the Housekeeper or a retire op |

The reverse lookup (who requires this) is never stored; it is derived from `inputs` across all
domains. Revision history is git. The index in `.local/ledger/index.sqlite3` is disposable and
records the git revision it covers (`python tools/ledger.py index --check`, `--rebuild`).

## Domains present

- `economics/`: the read-only baseline inventory of the IPO-timing chain
  (`Economics/pages/ipo-timing`, `Economics/graphs/ipo_age`, `Economics/research/IPOAGE-DATA`),
  30 records, all `inventoried`, purpose unknown, coverage unverified, inputs inferred from the
  build scripts (`basis: inferred-from-script`). Nothing under those folders was changed.
  Written 2026-11-26 by the ledger pilot (ticket T-0006).
