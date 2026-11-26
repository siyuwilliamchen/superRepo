# Codex: what the host reports about model and usage

Scope: tool `codex`. Owner: claude-code-quality-of-life. Updated: 2026-11-26.
Basis: runs on this machine with codex-cli 0.171.0-alpha.13.2, read by `tools/modelcheck.py` and
`tools/usage.py`; method in `system/methods/usage.md`. Observations of host behaviour only.

| Observation | Where it is read |
|---|---|
| `codex exec --json` names no model. Its events were `thread.started`, `turn.started`, `item.completed`, `turn.completed`. | the event stream |
| The saved session file names the model the client applied (`gpt-5.6-luna` when `-m gpt-5.6-luna` was given). No field read is the provider's own statement of which model answered. | `turn_context.model`, `thread_settings.model` in the rollout file |
| The host advertises its model choices in a local cache; a choice outside it is refused by the check before a worker starts. | `models_cache.json` in the Codex home directory |
| Usage arrives per turn in the event stream (`input_tokens`, `cached_input_tokens`, `cache_write_input_tokens`, `output_tokens`, `reasoning_output_tokens`) with no response id. The session file has a `token_usage_record` per provider response with its `resp_…` id. | `turn.completed.usage`; `token_usage_record.response_id` |
| The cached part is inside `input_tokens`: the CLI's own "tokens used" line read 3,541 for 13,904 input, 10,368 cached, 5 output. | plain `codex exec` output |
| `cache_write_input_tokens` was 0 in every run. | as above |
| A worker with `--sandbox read-only --ignore-user-config --ignore-rules` reported `sandbox: read-only`, `approval: never`. | plain `codex exec` header |

Uncertainty: whether a provider-reported model exists anywhere this tool does not read (the
host's own log database was deliberately not opened); whether `cache_write_input_tokens` sits
inside `input_tokens`; how a Codex child agent appears in a parent's capture (not observed).
Recheck: on any Codex upgrade. `tools/modelcheck.py` already reads a top-level `model` field in the
event stream if one appears, and the live Codex test then stops expecting `unknown`.
