"""Writes every fixture in this directory. All of it is invented.

No line here was copied from a real session, transcript or provider response: the ids are
`msg_SYN_*`, `resp_SYN_*`, `syn-*`, the models are `synth-*`, and every piece of text is the
one marker string below. Only the *shape* (which keys a host writes, and where) follows what
Claude Code 2.1.332 and codex-cli 0.171.0 were observed to write on 2026-11-26; see
system/methods/usage.md. Re-run after changing a shape:

    python tools/tests/fixtures/usage/make_fixtures.py

The counts are chosen so the books close: parent responses P1 + P2 and child response C1 add up
to the host's totals in the result event.

    response  input  output(final / live snapshot)  cache_read  cache_write
    P1           10       50 / 5                        200          100
    P2           12       80 / 3                        300           20
    C1            7       30 / 9                          0          400
    parent       22      130                            500          120   (result.usage)
    run          29      160                            500          520   (result.modelUsage)
    child total tokens 437                                               (task_notification)
"""
from pathlib import Path
import json

F = Path(__file__).resolve().parent
SID = "syn-session-0001"
TEXT = "SYNTHETIC-REPLY-TEXT"          # the tests assert this never reaches a usage record
M = "synth-claude-small-1"


def w(name, rows):
    p = F / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8", newline="\n")


def u(i, o, cr, cw):
    return {"input_tokens": i, "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr, "output_tokens": o}


def amsg(mid, model, content, usage, stop=None):
    return {"model": model, "id": mid, "type": "message", "role": "assistant", "content": content,
            "stop_reason": stop, "usage": usage}


tool = {"type": "tool_use", "id": "toolu_SYN_1", "name": "Agent", "input": {"prompt": TEXT}}
text = {"type": "text", "text": TEXT}
think = {"type": "thinking", "thinking": TEXT}

# ---- live stream of a headless run: one parent, one child. Assistant events are snapshots
# (stop_reason null, partial output); result events carry the host's exact totals.
w("claude_stream_parent_child.jsonl", [
    {"type": "system", "subtype": "init", "session_id": SID, "model": M, "tools": ["Agent"]},
    {"type": "assistant", "message": amsg("msg_SYN_P1", M, [tool], u(10, 5, 200, 100)),
     "parent_tool_use_id": None, "session_id": SID, "request_id": "req_SYN_P1", "timestamp": "2026-01-01T00:00:01Z"},
    {"type": "system", "subtype": "task_started", "task_id": "agentSYN1", "tool_use_id": "toolu_SYN_1",
     "subagent_type": "research-agent", "spawn_depth": 1, "session_id": SID},
    {"type": "assistant", "message": amsg("msg_SYN_C1", M, [text], u(7, 9, 0, 400)),
     "parent_tool_use_id": "toolu_SYN_1", "agent_id": "agentSYN1", "session_id": SID,
     "request_id": "req_SYN_C1", "timestamp": "2026-01-01T00:00:02Z"},
    {"type": "system", "subtype": "task_notification", "task_id": "agentSYN1", "tool_use_id": "toolu_SYN_1",
     "status": "completed", "usage": {"total_tokens": 437, "tool_uses": 0}, "session_id": SID},
    {"type": "assistant", "message": amsg("msg_SYN_P2", M, [think], u(12, 3, 300, 20)),
     "parent_tool_use_id": None, "session_id": SID, "request_id": "req_SYN_P2", "timestamp": "2026-01-01T00:00:03Z"},
    {"type": "assistant", "message": amsg("msg_SYN_P2", M, [text], u(12, 3, 300, 20)),
     "parent_tool_use_id": None, "session_id": SID, "request_id": "req_SYN_P2", "timestamp": "2026-01-01T00:00:03Z"},
    {"type": "result", "subtype": "success", "is_error": False, "session_id": SID, "uuid": "result-SYN-1",
     "result": TEXT, "usage": u(22, 130, 500, 120),
     "modelUsage": {M: {"inputTokens": 29, "outputTokens": 160, "cacheReadInputTokens": 500,
                        "cacheCreationInputTokens": 520}}},
])


# ---- the saved session of the same run: final counts, one line per content block
def tline(mid, content, usage, stop, side=False, agent=None, req=None):
    r = {"type": "assistant", "sessionId": SID, "isSidechain": side, "requestId": req,
         "timestamp": "2026-01-01T00:00:05Z", "message": amsg(mid, M, content, usage, stop)}
    if agent:
        r["agentId"] = agent
    return r


w("claude_transcript/syn-session-0001.jsonl", [
    {"type": "user", "sessionId": SID, "isSidechain": False, "message": {"role": "user", "content": TEXT}},
    tline("msg_SYN_P1", [tool], u(10, 50, 200, 100), "tool_use", req="req_SYN_P1"),
    tline("msg_SYN_P2", [think], u(12, 80, 300, 20), "end_turn", req="req_SYN_P2"),
    tline("msg_SYN_P2", [text], u(12, 80, 300, 20), "end_turn", req="req_SYN_P2"),
    {"type": "assistant", "sessionId": SID, "isSidechain": False,           # a host placeholder, not a response
     "message": {"model": "<synthetic>", "id": "msg_SYN_placeholder", "role": "assistant",
                 "content": [text], "usage": u(0, 0, 0, 0)}},
])
w("claude_transcript/syn-session-0001/subagents/agent-agentSYN1.jsonl", [
    tline("msg_SYN_C1", [think], u(7, 30, 0, 400), "end_turn", side=True, agent="agentSYN1", req="req_SYN_C1"),
    tline("msg_SYN_C1", [text], u(7, 30, 0, 400), "end_turn", side=True, agent="agentSYN1", req="req_SYN_C1"),
])
(F / "claude_transcript/syn-session-0001/subagents/agent-agentSYN1.meta.json").write_text(
    json.dumps({"agentType": "research-agent", "toolUseId": "toolu_SYN_1", "spawnDepth": 1, "model": M,
                "finished": True}) + "\n", encoding="utf-8", newline="\n")


# ---- model-check captures: what the host resolved against what the provider's responses name
def single(name, init_model, models, error=False):
    rows = [{"type": "system", "subtype": "init", "session_id": "syn-" + name, "model": init_model}]
    for n, m in enumerate(models):
        rows.append({"type": "assistant", "message": amsg(f"msg_SYN_{name}_{n}", m, [text], u(2, 4, 600, 0)),
                     "parent_tool_use_id": None, "session_id": "syn-" + name, "request_id": f"req_SYN_{name}_{n}"})
    rows.append({"type": "result", "subtype": "error_during_execution" if error else "success", "is_error": error,
                 "session_id": "syn-" + name, "uuid": "result-" + name,
                 "usage": u(2 * len(models), 4 * len(models), 600 * len(models), 0),
                 "modelUsage": {m: {"inputTokens": 2, "outputTokens": 4, "cacheReadInputTokens": 600,
                                    "cacheCreationInputTokens": 0} for m in models}})
    w(name + ".jsonl", rows)


single("claude_stream_small", "synth-claude-small-1", ["synth-claude-small-1"])
single("claude_stream_dated", "synth-claude-small-1-20260101", ["synth-claude-small-1-20260101"])
single("claude_stream_fallback", "synth-claude-large-1", ["synth-claude-small-1"])
single("claude_stream_mixed", "synth-claude-large-1", ["synth-claude-large-1", "synth-claude-small-1"])
single("claude_stream_error", "synth-claude-small-1", [], error=True)

# ---- Codex: the exec event stream names no model and no response id
w("codex_events.jsonl", [
    {"type": "thread.started", "thread_id": "syn-thread-0001"}, {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": TEXT}},
    {"type": "turn.completed", "usage": {"input_tokens": 1000, "cached_input_tokens": 600,
                                         "cache_write_input_tokens": 0, "output_tokens": 15,
                                         "reasoning_output_tokens": 0}}])
# an older shape: no cache_write key at all, so that count is unavailable, not zero
w("codex_events_no_cache_write.jsonl", [
    {"type": "thread.started", "thread_id": "syn-thread-0002"}, {"type": "turn.started"},
    {"type": "turn.completed", "usage": {"input_tokens": 500, "cached_input_tokens": 0, "output_tokens": 8}}])
w("codex_events_failed.jsonl", [
    {"type": "thread.started", "thread_id": "syn-thread-0003"}, {"type": "turn.started"},
    {"type": "turn.failed", "error": {"message": "synthetic failure"}}])


# the saved session of thread 0001: two provider responses in the one turn, each with its id
def rec(resp, i, c, o):
    return {"type": "token_usage_record", "timestamp": "2026-01-01T00:00:09Z",
            "payload": {"thread_id": "syn-thread-0001", "turn_id": "syn-turn-1", "response_id": resp,
                        "usage": {"input_tokens": i, "cached_input_tokens": c, "cache_write_input_tokens": 0,
                                  "output_tokens": o, "reasoning_output_tokens": 0}}}


w("codex_session.jsonl", [
    {"type": "session_meta", "payload": {"id": "syn-thread-0001", "model_provider": "openai",
                                          "base_instructions": {"text": TEXT}}},
    {"type": "turn_context", "payload": {"turn_id": "syn-turn-1", "model": "synth-gpt-small-1"}},
    {"type": "response_item", "payload": {"type": "message", "role": "user",
                                           "content": [{"type": "input_text", "text": TEXT}]}},
    rec("resp_SYN_1", 400, 200, 5), rec("resp_SYN_2", 600, 400, 10),
    {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": TEXT}}])
(F / "codex_models_cache.json").write_text(json.dumps(
    {"client_version": "0.0.0-synthetic", "models": [{"slug": "synth-gpt-small-1"}, {"slug": "synth-gpt-large-1"}]})
    + "\n", encoding="utf-8", newline="\n")

if __name__ == "__main__":
    print("\n".join(sorted(p.relative_to(F).as_posix() for p in F.rglob("*") if p.is_file())))
