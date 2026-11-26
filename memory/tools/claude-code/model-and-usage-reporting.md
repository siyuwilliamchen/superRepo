# Claude Code: what the host reports about model and usage

Scope: tool `claude-code`. Owner: claude-code-quality-of-life. Updated: 2026-11-26.
Basis: runs on this machine with Claude Code 2.1.332, read by `tools/modelcheck.py` and
`tools/usage.py`; method in `system/methods/usage.md`. These are observations of host behaviour,
not facts about any subject of research.

| Observation | Where it is read |
|---|---|
| A headless run names the model three times: the host's selection, the provider's response, the host's accounting. All three said `claude-haiku-5-5` for `--model haiku` and for `--model claude-haiku-5-5`. | stream `system/init .model`; assistant `message.model`; `result.modelUsage` keys |
| A subagent started without a named model answered with the parent's model. | the subagent's `message.model`; `modelNotNamed` in its `.meta.json` |
| The live stream shows a response before it ends: `stop_reason` is null and `output_tokens` is partial (16 shown, 120 final; 3 shown, 239 final; 24 shown, 52 final). Input and cache counts were already final. | assistant events of `--output-format stream-json` |
| The saved session file has the final counts, one line per content block, each repeating the same `message.id` and usage. | `<project>/<session>.jsonl`; subagents in `<session>/subagents/agent-<id>.jsonl` |
| `result.usage` covered the main loop only; `result.modelUsage` was cumulative and included the subagent; a `task_notification` gave the subagent's token sum. Parent plus child equalled the run total in all four categories. | `result` and `system/task_notification` events |
| A worker with `--tools "" --strict-mcp-config --safe-mode --permission-prompts none` ran with no tools and no MCP servers listed in its init event, and no permission denial. | stream `system/init .tools`, `.mcp_servers` |

Uncertainty: one machine, one CLI version, one day; one run with one subagent at depth 1. The
alias-to-id resolution is what was seen today, not a promise about tomorrow.
Recheck: on any Claude Code upgrade, and before relying on `result.usage` for a run with nested
subagents. `LIVEOS_LIVE_MODELCHECK=1 python -m unittest tools/tests/test_modelcheck.py` repeats
the model part.
