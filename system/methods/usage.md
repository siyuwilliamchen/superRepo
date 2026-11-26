# Which model answered, and what each agent used

Built 2026-11-26 on William's instruction. Two tools, one local store.
Code: `tools/modelcheck.py`, `tools/usage.py`. Tests: `tools/tests/test_modelcheck.py` (12, two of
them live and off by default), `tools/tests/test_usage.py` (11). Fixtures: `tools/tests/fixtures/usage/`,
all written by `make_fixtures.py` there; none is a real transcript.

## The rule

A role text may name a model and a ticket may expect a cost. Neither is a fact until the host and
the provider have said so. These tools read what the host wrote about a run and keep three
things strictly apart: what was asked, what the host says it did, and what the provider's own
response says. A value nobody reported is written as unknown or unavailable, with the reason. It
is never filled in from the request, and it is never zero.

## Where things live

| Path | What it is | In git? |
|---|---|---|
| `.local/usage/model-checks.jsonl` | One line per model check: requested, host-resolved, provider-reported, verdict, the list of unknowns | no (`.local/` is ignored) |
| `.local/usage/records.jsonl` | One line per provider response as a host wrote it, and the host's own totals; append-only | no |
| `.local/usage/agents.jsonl` | What each process was: parent, role, stage, outcome, requested model; observed or declared | no |
| `.local/usage/raw/` | A raw capture, only when `--keep-raw` is given (it holds the worker's reply) | no |
| `tools/tests/fixtures/usage/` | Synthetic captures in the hosts' shapes | yes |

The store holds identifiers, model names, counts and times. No prompt, reply or tool input is
copied into it; a test puts a marker string in every fixture and checks it never arrives.

## 1. Requested model against reported model

```
python tools/modelcheck.py choices --host codex            # what the host advertises
python tools/modelcheck.py run --host claude --model haiku
python tools/modelcheck.py run --host codex  --model gpt-5.6-luna [--persist]
python tools/modelcheck.py list
```

`run` starts the smallest worker the host allows: one fixed sentence in, two letters out.

| Host | How the worker is confined |
|---|---|
| Claude Code | `--tools ""` (no built-in tools), `--strict-mcp-config` (no MCP servers), `--safe-mode` (no hooks, skills, plugins, project instructions), `--permission-prompts none`, `--no-session-persistence`, a new empty directory |
| Codex | `--sandbox read-only`, `--ignore-user-config`, `--ignore-rules`, `--ephemeral` unless `--persist`, a new empty directory |

Neither command line carries a bypass flag. A Codex choice that is not in the host's own model
list is refused before any worker starts. The Claude CLI prints no model list, so a Claude choice
is shown to be supported only by the host running it.

Three names, three sources:

| Name | Claude Code | Codex |
|---|---|---|
| requested | the `--model` value | the `-m` value |
| host_resolved | `model` in the stream's `system/init` event | `turn_context.model` in the saved session file (needs `--persist`); the client's setting |
| provider_reported | `message.model` of each assistant event: the model field of the provider's response | **unknown**: no field in `codex exec --json` or in the session file is the provider's own statement |

Verdicts: `match`, `match_with_suffix` (the asked id plus a suffix such as a date), `alias_resolved`
(an alias was asked and the reported id names that family), `mismatch`, `mixed` (two models
answered one run), `unknown`. The verdict is drawn from provider_reported only. A host that says
it selected the right model while the response names another one is a `mismatch`; the test
`test_another_model_answering_is_a_mismatch` holds that line. Exit code 0 for the first three,
2 for `mismatch` and `mixed`, 3 for `unknown`.

### Observed, 2026-11-26 (Claude Code 2.1.332, codex-cli 0.171.0-alpha.13.2, this machine)

| Asked | Host says | Provider says | Verdict |
|---|---|---|---|
| Claude `haiku` (alias) | `claude-haiku-5-5` | `claude-haiku-5-5`, one response | `alias_resolved` |
| Claude `claude-haiku-5-5` | `claude-haiku-5-5` | `claude-haiku-5-5`, one response | `match` |
| Codex `gpt-5.6-luna`, `--persist` | `gpt-5.6-luna` (client-applied) | unknown | `unknown` |
| Codex `gpt-5.6-luna`, ephemeral | unknown (the event stream names no model) | unknown | `unknown` |

One more observation from the same day: a Claude subagent started without a named model reported
`claude-haiku-5-5`, the parent's model, in its own responses.

Unknowns the tool logged for Codex, in its words: the provider-reported model ("nothing read here
is the provider's own statement of which model answered"), the host-resolved model when the
session is not saved, and which model the usage was accounted to ("Codex reports usage per turn
without naming a model").

## 2. Usage per agent

```
python tools/usage.py ingest --format claude-stream     <capture>   [--role R --stage S --ticket T-0007 ...]
python tools/usage.py ingest --format claude-transcript <session.jsonl>
python tools/usage.py ingest --format codex-events      <capture>
python tools/usage.py ingest --format codex-session     <rollout.jsonl>
python tools/usage.py declare --run <run id> [--agent <id>] --role R --stage S --outcome O --parent <run>/<agent>
python tools/usage.py report [--run <run id>] [--json]
python tools/usage.py show --run <run id>
```

A **run** is one host session (a Claude session id, a Codex thread id). A **process** is one agent
inside a run: `main`, or a subagent by the id the host gave it. A process with a parent is a
**child**; the parent is found from the capture (the subagent's `tool_use` id leads back to the
agent that issued it) or declared with `--parent` for a worker started as its own run.

### The four categories

| Category | Anthropic field | Codex field |
|---|---|---|
| `input` (not cached) | `input_tokens` | `input_tokens - cached_input_tokens` |
| `output` | `output_tokens` | `output_tokens` |
| `cache_read` | `cache_read_input_tokens` | `cached_input_tokens` |
| `cache_write` | `cache_creation_input_tokens` | `cache_write_input_tokens`, as reported |

Codex counts the cached part inside `input_tokens`: its own "tokens used" line for a run with
13,904 input, 10,368 cached and 5 output read 3,541, which is input minus cached plus output.
Where a host reports a part of output separately (reasoning, thinking) it is kept as
`output_reasoning` and never added to a total.

### Counting each response once

The key is (provider, run, response id). Two things make a host write one response several times,
and both were seen in real captures:

- A Claude session file has one line per content block. A response with a thinking block and a
  text block is two lines with the same `message.id` and the same usage.
- The live stream of a headless Claude run shows a response before it is finished
  (`stop_reason` null). Its input and cache counts are already final; its output count is not.
  The saved session file has the final count (`stop_reason` set).

So: a final record replaces a snapshot of the same response; between two records of the same
finality the larger count of each category is kept. Ingesting a capture twice changes nothing.
The same response id under another run id is another response.

### The host's own totals are a check

| Host total | Covers | Used for |
|---|---|---|
| Claude `result.usage`, one per finished turn | The main loop only, not subagents | The main agent's figures when only snapshots were ingested; otherwise a check |
| Claude `result.modelUsage` | The whole run, cumulative, subagents included | The check that parent plus children add up |
| Claude `task_notification.usage.total_tokens` | One subagent, all four categories summed | A check on that child |
| Codex `turn.completed.usage` | One turn of the thread | The figures when the session file was not ingested; otherwise a check |

Each process's figures say where they came from (`basis`): `responses` (final per-response
records), `host_turn_totals`, `responses_partial` (snapshots only: the output count is printed
with `>=` and listed under unknown), or `unavailable`. A host total is never added on top of
responses.

### Role, stage, outcome

Each comes from the first of these that has it: a declaration (`--role`, `--stage`, `--outcome`),
the workflow ledger when a `--ticket` is given (stage is the ticket kind, role is the worker that
claimed it, outcome is the ticket's terminal state), the capture (role from the subagent type the
host named; outcome from the run's result or the subagent's completion status). What none of them
has is shown as `(unknown)` and listed. The accounting reads the ledger and never writes it.

### Unavailable is not zero

A count the host did not send is `null`: printed `n/a`, never 0. A sum over values gives the sum of
the known ones with `known` and `unavailable` beside it, and is `null` when nothing is known. A
total of the four categories exists only when all four do. A per-process average is the mean over
the processes that have the value, with the number that lack it stated. A process that was
declared but never reported anything appears in the report with four `n/a`.

### Observed on real runs, 2026-11-26

| Run | What was ingested | Result |
|---|---|---|
| Claude, parent that started one subagent | live stream only: 6 response lines, 4 responses | Parent exact from host turn totals: 8 / 541 / 14,519 / 4,029 (input / output / cache read / cache write). Child output `>=24`. Check against the host: "partly checked", output 565 against 593 |
| the same run | plus the saved session and the subagent's file: 12 lines, 4 responses | Child 2 / 52 / 0 / 3,909. Parent unchanged. Parent plus child equals the host's run total 10 / 593 / 14,519 / 7,938: reconciled in all four categories; child total 3,963 equals the host's figure for it |
| Codex, one turn, session saved | event stream and session file | One response with its `resp_…` id: 3,534 / 5 / 10,368 / 0; equals the turn total; reconciled |
| Codex, one turn, ephemeral | event stream only | Same counts from the turn total; no response id, no check possible |
| Claude, the fresh-session workspace reload (see the Conversationalist method) | stream and saved session: 6 lines, 2 responses | 4 / 266 / 8,285 / 3,704; reconciled |

## Limits

1. **Codex never tells this tool which model answered.** Every Codex check ends `unknown`. The
   tool reads a top-level `model` field in the event stream if a later CLI sends one.
2. **A live Claude stream alone understates output for subagents.** With
   `--no-session-persistence` there is no session file, so a child's output stays a lower bound.
   The parent is exact either way.
3. **The shapes are those of two CLI versions on one day.** `result.usage` covering the main loop
   only was seen on one run with one subagent. Subagents below depth 1 follow the same code path
   and are tested on a fixture at depth 1 only. A CLI upgrade needs the live tests re-run
   (`LIVEOS_LIVE_MODELCHECK=1`) and a look at one real capture.
4. **Codex child agents are not attributed.** A Codex worker is a child only when `--parent`
   says so. Codex `cache_write` was 0 in every observed run, so whether it sits inside
   `input_tokens` is not known; it is recorded as reported and not subtracted.
5. **Nothing ingests by itself.** No hook is registered; a run is in the store only after
   `ingest` is called on its capture, or after `modelcheck.py run`, which ingests its own.
6. **No money.** No price is stored or computed (`system/models/README.md` forbids invented
   prices); the host's own cost figure is not copied.
7. **`alias_resolved` does not mean newest.** It means the reported id names the alias's family.
8. **Stage is not observable for a subagent.** It is declared or it is `(unknown)`.
