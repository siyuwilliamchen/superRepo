# superRepo: the LiveOS agent layer

The shared operating layer for William's vaults: agent roles, their host adapters, the methods they
follow, the Coordinator that routes work between them, the Conversationalist that talks with
William, the watchdog, the ledger pilot and the publication handoff, with their tests. Started
2026-11-26 from the components finished that day in the SiyuJournal worktree
`.claude/worktrees/conversationalist`.

What this repository is not: it holds no domain content (no field folders, research cards,
pages, claim maps or ledger inventories of a vault) and no private session data
(`sessions/` is ignored). Those stay in each vault; this repository is the machinery.

## The shape

| Role | What it is | Where |
|---|---|---|
| **Conversationalist** | The one user-facing role. Talks with William, decides what to raise, files every request, brings results back, freezes the writing brief. | `system/agents/conversationalist.md`, `tools/conversationalist.py` |
| **Coordinator** | Durable routing and recovery, ordinary code: one ticket per request key, receipts, leases, exactly-once follow-on, delivery to the session inbox, stall guard. The only writer of `workflow/`. | `system/methods/coordinator.md`, `tools/coordinator.py` |
| **Watchdog** | Independent of both: notices a dead or late Coordinator service, dead relays, interrupted jobs and overdue attempts; escalates through the Coordinator only. | `system/methods/watchdog.md`, `tools/watchdog.py` |
| Researcher, Interpreter, Writer and reviewers | Workers the Coordinator routes to by capability. | `system/agents/`, `workflow/roster.json` |
| Ledger and Housekeeper (pilot) | Stable ids and required-input chains for durable material; eligible / held / unresolved; verified retire and restore. Fixture-tested only. | `system/methods/ledger.md`, `tools/ledger.py` |
| Publication | A frozen brief becomes a package of sources and a deterministic HTML and PDF edition outside git. | `system/methods/publication.md`, `tools/publish.py` |

Start with `system/README.md`, then `system/methods/README.md`. The two designs this
implements are in `docs/design/`.

## Running it

```
python -m unittest discover -s tools/tests -p "test_*.py" -v     # 64 tests
python tools/coordinator.py status                                # the ticket ledger
python tools/conversationalist.py open --session <S> --topic <topic>
python tools/watchdog.py serve --once                             # one independent tick
```

Every tool takes `LIVEOS_ROOT` to point at another root (the tests use a scratch one). Runtime
state (`.local/`), sessions, generated editions and audio are ignored by git.

## Where it sits against a vault

A vault (a domain repository) keeps its field folders, topics, claim maps and pages. It is an
explicit external input: registered in `config/vaults.json`, resolved by `tools/vaults.py`, never
assumed. A ticket's `scope_ref` such as `topics/<topic>/index.md` is looked up under this
repository first, then under each registered vault; role texts write a vault path as
`<vault>/...`. With no vault registered the tools and all tests still run (the ledger baseline and
the real-map tests skip and say why). `python tools/vaults.py list` shows what this machine has.
