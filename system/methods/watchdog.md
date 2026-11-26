# The independent watchdog

Part of "LiveOS research through conversation" (William's design, 2026-11-25, Draft 1, section 4
"Failure and recovery rules" and acceptance case 5 "Liveness without noise"). Built 2026-11-26
under ticket T-0005. Code: `tools/watchdog.py`. Tests: `tools/tests/test_watchdog.py` (9 tests).
Deadlines: `workflow/deadlines.json`. Scheduled-task script: `tools/register_watchdog_task.ps1`
(not run; William's decision). Sits beside the [Coordinator](coordinator.md) and the
[Conversationalist](conversationalist.md).

## The rule

The Coordinator's `reconcile` is the stall guard, but it only runs where something runs it: at a
completion, at a session start, or in a service that dies with the session that started it. The
watchdog is the thing that is **not** the conversation, **not** the Coordinator service and
**not** a worker. It reads runtime state and the ledger, says what is dead, late, interrupted or
overdue, and when something must change in the ledger it asks the Coordinator through its command
line. It never writes a file under `workflow/` itself, never kills a worker and never fails a
ticket.

Two things are kept apart, as the design asks:

| | Question | Who answers it | How |
|---|---|---|---|
| **Liveness** | Is the worker still there and still talking? | the Coordinator | process check; lease (30 min silent → requeue); stall flag (15 min silent → flagged once) |
| **Progress** | Is the work going to end? | the watchdog | a deadline per ticket kind, measured from the claim; past it, one diagnose ticket |

A 20-minute job that reports progress is healthy to both. A worker that reports "searching again"
every five minutes for three hours is healthy to the Coordinator and overdue to the watchdog.

## Where things live

| Path | What it is | In git? |
|---|---|---|
| `workflow/deadlines.json` | One deadline per ticket kind, in seconds, each with its reason in plain words; thresholds for the service, relay and run checks | yes |
| `.local/workflow/watchdog.json` | The watchdog's own heartbeat: pid, time, tick count, mode, last findings and actions, which attempts it has already escalated | no |
| `.local/workflow/watchdog.log` | One JSON line per tick that found something or failed; quiet ticks write nothing here | no |
| `.local/workflow/coordinator.json`, `relays/<S>.json`, `leases/*.json`, `.local/runs/*.json` | What it reads: the heartbeats of the service, the relays, the leases and the shell-job ledger | no |

## What one tick does

```
python tools/watchdog.py serve --once        # one tick; exit 0 quiet, 1 attention, 2 the tick failed
python tools/watchdog.py serve               # loop, every 300 s
python tools/watchdog.py status              # the last tick's findings
python tools/watchdog.py deadlines           # the deadline table with reasons
```

| Check | What it reads | What counts as wrong | What the watchdog does |
|---|---|---|---|
| Coordinator service | `.local/workflow/coordinator.json`, open tickets | **dead**: heartbeat pid gone. **late**: pid alive but no tick for 3 intervals. "never started" is not a fault in this checkout | if work is open and the service is not known to be running, runs `coordinator.py reconcile --json --quiet` in its place and reports the Coordinator's actions; prints the start command |
| Relays | `.local/workflow/relays/<S>.json`, `sessions/<S>/session.json`, `sessions/<S>/inbox.jsonl` | **dead**: pid gone. **late**: no tick for 6 intervals + 5 s (the Conversationalist's own rule). **not started** with unread results waiting | reports, with the unread count and the exact restart command; needs attention only when unread results wait. Starts no process |
| run.py jobs | `.local/runs/*.json` | **interrupted**: wrapper pid gone or no heartbeat for 90 s while "running". **stalled**: heartbeat fresh but no CPU or output for 15 min (run.py's own thresholds) | reports with log and resume command; if a lease names the run, says that reconcile requeues its ticket |
| Deadlines | every claimed ticket's `claimed` event (lease as fallback), `workflow/deadlines.json` | **overdue**: the current attempt has been claimed longer than its kind's deadline | once per attempt: `coordinator.py submit --kind diagnose --sender watchdog --request-key watchdog:deadline:<T>#a<n>` with the parent's scope, session and turn, so the answer lands in the session inbox. The overdue ticket is not touched |

Every finding carries `why` (plain words), `did` (what the watchdog did) and `next` (the command a
person would run). The exit code of `serve --once` is 1 only for findings marked as needing
attention, so a scheduled task's history shows at a glance whether anything was wrong.

## Deadlines (first guesses, 2026-11-26; William sets them)

| Kind | Deadline | Reason, as written in the file |
|---|---|---|
| research | 90 min | a bounded question starts at one topic index and reads a handful of sources; past this the worker is usually repeating a search or has widened the question |
| interpret | 45 min | works from evidence already gathered; longer means it has become research |
| write | 2 h | a page set from a frozen brief including build and checks; longer means the brief was not frozen or checks keep failing |
| diagnose | 30 min | reads lifecycle records and names a cause; longer means it has become an investigation |
| build | 6 h | code, tests, method and handoff; the builds of 2026-11-25/26 took two to four hours |

A kind missing from the file gets `default_deadline_seconds` (2 h); a missing file gets built-in
defaults and `deadlines` says so.

## Bounded, idempotent escalation

- **One diagnose ticket per attempt.** The request key `watchdog:deadline:<ticket>#a<attempt>` is
  deterministic. The Coordinator's `submit` returns the existing ticket for a repeated key, so a
  tick that crashes after submitting, a wiped heartbeat file, or a hundred further ticks produce
  one ticket. Tested: three further ticks and a tick with the heartbeat deleted leave exactly one.
- **A new attempt is a new deadline.** If the Coordinator requeues the ticket and another worker
  claims it, the attempt number changes and the clock restarts.
- **Nothing is killed.** The watchdog cannot tell a looping worker from a slow one; the diagnose
  ticket asks a diagnostic worker to decide between "let it continue", "fail with `--force` and
  requeue" or "re-scope". The spec's bounded retries live in the Coordinator (3 attempts, then
  fail and diagnose); the watchdog adds the deadline route to the same diagnostics.
- **Reconcile is the other route.** When the service is not running, the watchdog's tick is the
  minute check. It carries no logic of its own about leases or children; the Coordinator's code
  runs, as a new process, under its own lock.

## An idle tick

Reads files, writes `.local/workflow/watchdog.json`, nothing else: no log line, no file under
`workflow/` or `sessions/`, no model call, no git command. Tested byte-for-byte. When it stands in
for the service it also runs `reconcile`, which on an idle ledger is itself byte-identical (the
Coordinator's own test) and leaves only the lock file's creation and removal under `.local/`.

## Running it independently of the conversation

A process started from a chat dies with the chat. Two ways to make the watchdog outlive it:

1. **Windows Task Scheduler** (the intended way): `tools/register_watchdog_task.ps1` prints the
   exact task it would create and registers nothing until `-Register` is passed. Task
   `\SiyuOS\SiyuOS LiveOS Watchdog`: `python.exe "<repo>\tools\watchdog.py" serve --once`,
   working directory the repo root, every 5 minutes, as the logged-on user, lowest privileges,
   skipped while a previous tick still runs, 10-minute limit. It writes nothing on screen;
   `python tools/watchdog.py status` shows the last tick. **This worker did not run the script;
   registering a task on the machine is William's decision.**
2. **Under the run ledger**, for a session that wants it now:
   `python tools/run.py start watchdog -- python tools/watchdog.py serve`. Its death is then
   reported at the next session start like any other job (and by the next scheduled tick, if
   there is one).

The session-start hook (`.claude/hooks/session_runs.py`) reads the run ledger but not yet the
watchdog's heartbeat; see the proposed changes below.

## Verified and not verified

| Claim | Status |
|---|---|
| Dead service heartbeat detected; reconcile run in its place; a dead worker's ticket requeued by the Coordinator, not by the watchdog | verified, test 1 |
| Late service heartbeat reported; idle reconcile changes nothing | verified, test 2 |
| Dead relay heartbeat detected with unread count and restart command; live relay left alone | verified, tests 3–4 |
| Interrupted run.py job reported with its resume command | verified, test 5 (synthetic record) |
| Overdue research ticket escalated to exactly one diagnose ticket through the Coordinator; idempotent across ticks and across a lost heartbeat; the overdue ticket untouched | verified, test 6 |
| Healthy two-hour build within its six-hour deadline, with a live service: no findings, ledger byte-identical | verified, test 7 |
| Idle tick: only `.local/workflow/watchdog.json` new; ledger byte-identical over two ticks | verified, test 8 |
| One live tick in this worktree (2026-11-26 05:19 UTC): all quiet, service not running, watchdog ran reconcile, exit 0 | verified once |
| The scheduled task runs every 5 minutes and survives a session's end | **unverified**: the script was parse-checked only, never run |
| The deadline numbers fit real work | **unverified**: first guesses from four builds and two probes |
| Stalled (wedged) run.py job detection | the same thresholds as run.py, not separately tested with a live wedged process |

## Where this departs from the design

- **The watchdog does not restart anything.** The design's "route to diagnostics" is kept; an
  automatic restart of a relay or the service would be a process spawn from a scheduled task and
  is left to William or to a later ticket.
- **Deadlines measure the claim, not the question.** A ticket requeued twice gets three clocks.
  The Coordinator's 3-attempt limit bounds the total.
- **A Coordinator run as `serve --once` from a task would look dead** to the watchdog, because its
  heartbeat has no `mode` field and its pid has exited. The watchdog already honours
  `"mode": "once"` if the Coordinator starts writing it (proposal below).

## Proposed changes to files this worker could not edit

| File | Change | Why |
|---|---|---|
| `.claude/hooks/session_runs.py` | after the run-ledger check, read `.local/workflow/watchdog.json`; add one line "watchdog: last tick N ago, K findings" or "watchdog: never run" to the session context | the new session learns whether anyone was watching while it was away |
| `tools/coordinator.py` `serve` | write `"mode": "once" if args.once else "serve"` into `coordinator.json` | lets the watchdog (and `status`) tell a one-shot tick from a dead service |
| `tools/coordinator.py` `status` / `health` | add a `watchdog` line/field from `.local/workflow/watchdog.json` | one place to see both guards |
| `system/methods/coordinator.md` | in "Where this departs": replace "The service is not yet independent of the session" with a pointer to this note | the gap is now filled by the watchdog, pending the task registration |
| `system/methods/README.md` | row: "Watch the watchers \| [Watchdog](watchdog.md) \| dead or late service and relays, interrupted jobs, overdue attempts; reconcile or one diagnose ticket through the Coordinator; nothing written by hand" | index |
| `workflow/roster.json` | a `watchdog` entry like `conversationalist`: `capabilities: []`, `requests: ["diagnose"]`, `tool: tools/watchdog.py`, `writes: [".local/workflow/watchdog.json"]`, note "a requester, not a worker" | the roster is the list of who may ask the Coordinator for what |
| `tools/README.md` | one line for `watchdog.py` and `register_watchdog_task.ps1` | tools index |
