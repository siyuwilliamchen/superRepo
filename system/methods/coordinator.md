# The Coordinator and the workflow queue

Phase 1 of "LiveOS research through conversation" (William's design, 2026-11-25, Draft 1).
Built 2026-11-25. Code: `tools/coordinator.py`. Tests: `tools/tests/test_coordinator.py`.
Shell jobs use the companion ledger `tools/run.py`.

## The rule

Roles never hand work to each other directly. A role submits a request to the Coordinator,
gets a receipt, and the result comes back to the place the request named. The Coordinator is
ordinary code: validate, persist, claim, retry, reconcile, deliver. No model call is made by it.

## Where things live

| Path | What it is | In git? |
|---|---|---|
| `workflow/roster.json` | Roles, the capabilities each advertises, adapters, read/write scopes | yes |
| `workflow/outbox/<kind>/<id>.json` | One immutable request. Kinds: `research`, `interpret`, `write`, `diagnose` | yes |
| `workflow/events/<id>/<seq>-<event>.json` | Ordered lifecycle records. The state of a ticket is derived from these, never stored | yes |
| `sessions/<session>/inbox.jsonl` | Results returned to a conversation, each named by the question first asked | yes |
| `topics/<topic>/index.md` | Where a worker starts. A request whose topic index does not exist is refused | yes |
| `.local/workflow/leases/`, `coordinator.json` | Leases, progress, the service heartbeat: runtime state | no |

## For a worker (any role, any provider)

```
python tools/coordinator.py claim --worker <role-name> [--kind research] [--pid <pid> | --run-id <id>]
python tools/coordinator.py progress <ticket> --attempt-id <id> --milestone "reading source 3 of 9"
python tools/coordinator.py complete <ticket> --attempt-id <id> --summary "..." \
       [--claims C-07,C-12] [--sources "..."] [--uncertainty "..."] [--artifact <path>]
python tools/coordinator.py fail <ticket> --attempt-id <id> --reason "..." [--retry] [--blocker "..."]
```

1. **Claim** returns the question, the `scope_ref` to start from, the `done_when` test, and an
   `attempt_id`. Keep the attempt id: it is your right to publish.
2. **Report progress at meaningful milestones.** Silence for 15 minutes flags the ticket as
   stalled; silence for 30 minutes ends the lease and the ticket is requeued.
3. **Complete or fail explicitly.** A result from an attempt that no longer holds the lease is
   refused. A second completion of a finished ticket is ignored.
4. If you cannot finish, `fail` with the last successful step, what is missing, and a suggested
   next action. Do not go quiet.

A worker that is a process should pass `--pid` or run under `tools/run.py` and pass `--run-id`;
its death is then noticed at once. An agent worker has no process to check, so only the lease
clock applies to it.

## For a role that asks

```
python tools/coordinator.py submit --kind research --topic <topic> --session <S> --turn <u> \
       --request-key "<S>/<u>/<slug>" --question "..." --done-when "..." [--after-success interpret]
```

The receipt carries the ticket id. Submitting again with the same `--request-key` returns the
same ticket, so a retry after a lost connection is safe. `--after-success interpret` queues the
interpretation automatically when the research lands, exactly once; the research result is then
not delivered on its own, and the interpretation carries the answer back.

## The stall guard

`reconcile` is the guard. It is idempotent and does nothing when idle. It runs in three places,
so no single one has to stay alive:

- **at every completion and failure** (the immediate event);
- **at every session start**, through `.claude/hooks/session_runs.py`;
- **every minute**, when the service runs: `python tools/run.py start coordinator -- python tools/coordinator.py serve`.

| What it finds | What it does |
|---|---|
| Claimed ticket, worker process gone | Requeue for a new attempt |
| Claimed ticket, lease past 30 minutes | Requeue; after 3 attempts, fail it and open one `diagnose` ticket |
| Claimed ticket, alive but no progress for 15 minutes | Record `stalled` once per attempt. Flagged, not killed: a long job can be healthy |
| Completed ticket whose follow-on was never created | Create it, with a deterministic key, so a crash cannot make two |
| Finished ticket never delivered | Put it in the session inbox, once |

`python tools/coordinator.py status` shows the queue and whether the service is running.
`health` gives the same as JSON and exits non-zero when something needs attention.

## Where this departs from the design

- **Serialisation uses a lock file and atomic file replacement, not atomic git ref updates.**
  The expected-revision check is each ticket's event sequence number. Committing the ledger to
  git is a separate step. Reason: a commit per transition is slow on this machine and would put
  heartbeat-rate traffic near git; the design's guarantee (one writer, no lost update, idempotent
  retry) is kept and tested.
- **The service is not yet independent of the session.** A process started from a session dies
  with it. The three reconcile points above cover that for now. Since 2026-11-26 the independent
  watchdog (`system/methods/watchdog.md`, `tools/watchdog.py`) watches the service, the relays,
  the run ledger and overdue attempts, and runs reconcile in the service's place; its scheduled
  task (`tools/register_watchdog_task.ps1`) is written but not registered, pending William's approval.
- **Built 2026-11-26 on top of this:** the Conversationalist's durable side (session turns,
  corrections, outline, coverage, acknowledgment levels, catch-up, return relay, checkpoint,
  frozen brief): `system/methods/conversationalist.md`. A fifth ticket kind, `build`, records a
  development assignment from William in this same ledger; the `developer` role in the roster
  advertises it.
- **Built 2026-11-26 by the four follow-on tickets (T-0004 to T-0007 in the worktree ledger):**
  the Interpreter and its claim maps (`system/agents/interpreter.md`, `tools/claimmap.py`), the
  watchdog (`system/methods/watchdog.md`), the scratch ledger pilot (`system/methods/ledger.md`),
  and the publication handoff with its deterministic build (`system/methods/publication.md`).
- **Not built yet:** provider adapters beyond Claude Code and Codex (phase 5), a verified voice
  client, automatic commit and remote acknowledgment.
