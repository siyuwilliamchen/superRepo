# The Conversationalist's durable side

Phases 2–3 of "LiveOS research through conversation" (William's design, 2026-11-25, Draft 1,
filed at `Project_Management/inputs/William_2026-11-25_LiveOS_Research_Conversation_Spec.md`).
Built 2026-11-25/26 on top of the Coordinator (`system/methods/coordinator.md`).
Code: `tools/conversationalist.py`. Tests: `tools/tests/test_conversationalist.py` (11 tests) and,
for the workspace added 2026-11-26, `tools/tests/test_workspace.py` (7 tests).
Role text: `system/agents/conversationalist.md`; adapters `.claude/agents/conversationalist.md`,
`.codex/agents/conversationalist.toml`. Roster entry with client declarations: `workflow/roster.json`.

## The rule

The model that plays the partner talks; this tool keeps every durable part of the conversation on
disk so that a restart, a provider switch or a dead device loses nothing. It never writes the
workflow ledger: every ticket goes to `tools/coordinator.py` as a separate process, and the
Coordinator's receipt is the only thing the partner may call "recorded".

## Where things live

| Path | What it is | In git? |
|---|---|---|
| `sessions/<S>/session.json` | Governing question and its revisions, counters, the two cursors (incorporated, relayed), the declared notify adapter | yes |
| `sessions/<S>/turns/<segment>.jsonl` | Every turn, stable id `u-N`, speaker, kind (`turn`, `correction`, `reentry`), the turn it corrects; segment size fixed at creation | yes |
| `sessions/<S>/outline.jsonl` | William's working outline: append-only entries `O-N` with originating turn and disposition (explicit / confirmed / inferred), plus correction notes; the current view is derived | yes |
| `sessions/<S>/coverage.json` | One line per point: unraised, raised, understood, contested, deferred, commissioned, returned | yes |
| `sessions/<S>/tickets.jsonl`, `pending/` | Requests this session filed, with their acknowledgment; a pending file is the local acknowledgment | yes |
| `sessions/<S>/inbox.jsonl` | Written by the Coordinator; the Conversationalist owns the `read` flag | yes |
| `sessions/<S>/spoken.jsonl`, `relays.jsonl` | What was said aloud (and how), what was pushed to a chat | yes |
| `sessions/<S>/checkpoints/`, `briefs/` | Round checkpoints; frozen writing briefs | yes |
| `sessions/<S>/decisions.jsonl` | William's decisions: append-only `D-N`, each with the turn it was made in and the decision it replaces, if any | see note |
| `sessions/workspace.json` | The workspace pointer: which session and checkpoint a fresh session loads first | see note |
| `.local/workflow/relays/<S>.json`, `.local/workflow/spoken/` | Relay heartbeat; synthesized audio | no |

Note on the last column: it describes the vault worktree this was built in. In this repository
(superRepo) `sessions/` is ignored by git, so no session file, decision or workspace pointer is
tracked here; a test checks it (`test_workspace_and_sessions_are_ignored_by_git`).

## Acknowledgment levels, told apart

The design says a successful acknowledgment is a committed request at the shared remote. This
checkout has no remote and commits nothing without William's word, so the partner must say less.
`ask` and `receipt` report what is actually true, in this order:

| Level | What has happened | What the partner says |
|---|---|---|
| `local` | The request is saved in `sessions/<S>/pending/`; the Coordinator has not accepted it | "saved here; the shared ledger has not taken it yet; I will keep retrying with the same key" |
| `ledger` | The Coordinator persisted `workflow/outbox/<kind>/<id>.json` and issued a receipt | "recorded as T-0142 … in the local ledger, not yet shared" |
| `committed` | That file is in a git commit (checked with `git log -- <path>`) | "committed here, not yet on the shared remote" |
| `remote` | The commit is on a remote-tracking branch (`git branch -r --contains`) | "recorded as T-0142" |

A lost connection (`--offline` in tests) leaves the request at `local`; `flush` retries with the
original request key, and the Coordinator's idempotency means one ticket however often it is
retried. In this checkout every real ticket stops at `ledger` (see Approvals).

## Delayed results: once, with provenance, at a pause

`catchup` reads the session inbox past the shared cursor, orders what it finds (results touching
the current outline's claims first, superseded ones last), appends one `reentry` partner turn per
result whose `refs` carry the provenance (ticket, the ticket it answers, the question as asked,
when, the originating turn, question revision, input and output git revisions, claims changed,
sources), prints the one or two sentences to say, moves the cursor, and marks the inbox lines
read so the Coordinator's `health` agrees. A second run, or a run after a restart, delivers
nothing twice. A result for a superseded question revision is reported as "an earlier version of
the question" and does not move coverage; the ticket stays attributable to its revision.

## Speech: simulated against actual

| Mode | What the record says | Verified |
|---|---|---|
| `simulated` | `delivery: simulated`, text only, nothing synthesized | yes |
| `sapi-wav` | `delivery: actual`, Windows System.Speech synthesized the words into a `.wav` (bytes recorded); nobody has heard it | yes: 558 KB file for the probe re-entry, 2026-11-26; the test asserts synthesis |
| `sapi-speaker` | `delivery: actual`, played through the default audio device | not run; a listener is never verified by the tool |

Installed voices: Microsoft David and Zira (en-US), Huihui (zh-CN); Chinese text selects the
zh-CN voice. No voice client (Grokbot or other) exists; text is the equivalent interface.

## The return relay (William's follow-up, request key `liveos-conversationalist-return-relay`)

`relay --session <S> --notify-file <path>` (or `--notify-cmd <argv>`) is a small process that
watches the session inbox and, for each landed result past the relay cursor, writes one chat
notification (JSON line) or runs the declared command with it on stdin. It polls the file every
two seconds; no conversation turn and no model call is spent. The conversation still incorporates
the result only through `catchup`, so an offline session finds it unread next time.

**Live run, 2026-11-26 05:04 UTC, this Claude Code chat.** The relay ran under
`tools/run.py` (`20261125-210351-relay-S-dev`); a Claude Code `Monitor` tailed the notify file.
A worker completed the no-op probe ticket T-0003 at 05:04:44; the relay wrote one notification
at 05:04:45; the chat received it as a monitor event with no polling by the conversation. The
inbox item stayed unread until `catchup` at 05:05 took it up (re-entry turn `u-3`). A restarted
relay (`--once`) notified nothing more. The unit test repeats the same sequence against a
file standing in for the chat and checks exactly one notification, no speech, unread until
catch-up.

What is and is not shown: chat delivery into a **Claude Code** session is verified by this run
(it needs a Monitor armed in that session, which only that session can do). Delivery into a
**Codex** chat was reported by William as achieved once by a Claude completion relay; this
worker did not reproduce it and the roster says so. Spoken playback remains unverified.

## Checkpoint and brief

`checkpoint` writes the governing question and history, current outline, confirmed connections,
contested and deferred points, open tickets with acknowledgment, and the last delivered event;
`open` builds the next session's context from the latest checkpoint plus everything newer.
`brief` refuses while an outstanding ticket's claims intersect the lead claims, naming the ticket
and the claims; `--accept-limitation` writes the limitation into the brief and files the `write`
ticket. No draft exists before the authorising turn.

## The workspace: what a fresh session loads first (2026-11-26)

A session that has just started knows no session id and remembers nothing. `open` needs the id;
the workspace does not.

```
python tools/conversationalist.py decide --session <S> --turn u-12 --text "..." [--supersedes D-2]
python tools/conversationalist.py checkpoint --session <S> --note "..." --next "the next action, one sentence"
python tools/conversationalist.py workspace [--session <S>] [--json]
```

It is built on the checkpoints, not beside them. `checkpoint` now also stores the current
decisions and the next action, and writes `sessions/workspace.json`, a pointer to that session
and checkpoint with the checkpoint file's hash. `workspace` answers four things:

| Part | Where it comes from |
|---|---|
| Current topic | The session's topic, its index path, the governing question and revision |
| Decisions | `decisions.jsonl`, replaced ones left out; one made after the checkpoint is marked so |
| Pending work | Read again at load time, not copied from the checkpoint: open tickets with their state in the ledger and their acknowledgment level, results in the inbox not yet brought in, requests saved locally, contested and deferred points |
| Next action | The sentence recorded at the checkpoint, unless something must come first: unread results (then `catchup`), or locally saved requests (then `flush`). The recorded action is kept as `then`. With nothing recorded, the view says so and names what is still out |

A pointer that is missing, unreadable, names a session that is not on disk, or is older than the
newest checkpoint is not trusted: the newest checkpoint on disk is used and the view says which
happened. With no checkpoint anywhere the answer is `workspace: empty`, not an invented state.
When two conversations exist, the one checkpointed last is the workspace; `--session` names another.

**Verified.** `test_workspace.py` runs every step as a new process against a scratch root, so
each call is a restart: the reload with no session id; a ticket finished and a result landed
after the checkpoint; a decision made later; the pointer deleted, corrupted, pointed at a missing
session and left stale; two sessions; the empty case. **Live run, 2026-11-26:** a new Claude Code
session (`claude -p --model haiku --safe-mode`, built-in tools limited to Bash, one allowed
command, prompts denied) was told only to run `python tools/conversationalist.py workspace`
against a scratch root holding one invented conversation, and to say where things stood. It ran
that one command (no permission denial) and restated the topic and question, both decisions, the
open research ticket and the deferred point, and the recorded next action, each correctly.

**Limits.** A decision exists only if the partner records it with `decide`; nothing extracts
decisions from the turns. The next action is whatever one sentence was given at the checkpoint.
The live reload was run on Claude Code with a small model and invented content; a Codex session
playing the Conversationalist has not been tried.

## Where this departs from the design

- **Acknowledgment stops at `ledger`.** Nothing is committed or pushed automatically (CLAUDE.md:
  nothing is committed unless William asks; no remote is configured). The levels above make the
  gap visible instead of hiding it.
- **The relay polls a file; the Coordinator does not call out.** The design's "lightweight
  notification to the active adapter" is implemented beside the Coordinator, not inside it, so the
  Coordinator stays untouched by this work apart from one additive ticket kind.
- **`build` is a fifth ticket kind** so a development assignment from William is recorded in the
  same ledger as research; the `developer` role advertises it. The design names four kinds and
  says others exist.
- **Interpreter's map is read-only.** `open` reads the latest map through `tools/claimmap.py`
  (built the same day under T-0004) and lists the important claims not yet in coverage, each
  with what William would misunderstand if he missed it: the seed of the "unraised" view. For
  `borrowing-consent` that is `claims/map-r2.json`, 16 claims, 10 important ones unraised at the
  start of a fresh session. A topic without a map says so.
- **Segment size is fixed per session**, not global, so a later host cannot re-split old turns.

## Approvals still needed from William

1. **Commit and remote.** The ledger (`workflow/`, `sessions/`) is uncommitted and there is no git
   remote; `committed` and `remote` acknowledgment cannot happen until he decides both.
2. **Adopting this work.** It was built in the worktree `.claude/worktrees/conversationalist`
   (branch `worktree-conversationalist`), nothing committed. The main checkout's untracked
   Coordinator files differ from the worktree copies by the one `build` line in
   `tools/coordinator.py`, the two roster roles, and the coordinator method's "built on top" note.
3. **The relay as a standing process.** A relay per active session, and the Coordinator's minute
   check, need a scheduled task or a service on this machine to outlive the session that started them.
4. **Speaker output.** `--voice sapi-speaker` plays sound on this machine; it has not been run.
5. **Hooks.** A `PostToolUse` or `SessionStart` hook that arms a Monitor automatically needs the
   `hooks` block in `.claude/settings.json`, which only William adds.
6. **The main-checkout ticket T-0001** (`liveos-conversationalist-return-relay`) is still
   `queued` there; this worker did not write into the main checkout. Its work is done under the
   worktree's T-0002 and described above.
