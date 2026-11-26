"""Local usage accounting, per agent: what each worker process actually consumed.

Reads what a host wrote about a run (never the conversation text), keeps one record per
provider response, and reports totals per agent, child against parent, by role, stage and
outcome, in aggregate and averaged per process. Method, verified behaviour and limits:
system/methods/usage.md.

  ingest    read one host capture and append its records (idempotent: the report deduplicates)
              --format claude-stream      `claude -p --output-format stream-json --verbose`
              --format claude-transcript  a saved Claude Code session file (subagents found beside it)
              --format codex-events       `codex exec --json`
              --format codex-session      a saved Codex session (rollout) file
  declare   say what a process was: role, stage, outcome, parent, requested model, ticket
  report    totals, child against parent, by role / stage / outcome, per-process averages
  show      the deduplicated records of one run

Three rules the numbers follow:

1. One provider response is counted once per run. The key is (provider, run, response id). A host
   that writes the same response several times (one line per content block; a live snapshot and
   then the saved final) contributes one record: a final record replaces a snapshot, otherwise
   the larger count of each category is kept.
2. Unavailable is not zero. A count the host did not report is null and stays null: a sum over
   nothing known is null, and every figure says how many values it holds and how many it lacks.
3. A host's own totals are a check, never added on top. They stand in for an agent's figures
   only when that agent's responses are missing or are live snapshots whose output is partial.

Everything is written under .local/usage/ (git-ignored). Records hold identifiers, model names,
counts and times; no prompt, reply or tool input is ever copied.
"""
from pathlib import Path
import argparse, datetime as dt, json, os, sys

ROOT = Path(os.environ.get("LIVEOS_ROOT") or Path(__file__).resolve().parents[1]).resolve()
USAGE = ROOT / ".local" / "usage"
RECORDS = USAGE / "records.jsonl"
AGENTS = USAGE / "agents.jsonl"

CATEGORIES = ("input", "output", "cache_read", "cache_write")
EXTRA = ("output_reasoning",)            # a part of output where a host reports it; never added to a total
FORMATS = ("claude-stream", "claude-transcript", "codex-events", "codex-session")
MAIN = "main"
UNKNOWN = "(unknown)"
AGENT_FIELDS = ("parent", "role", "stage", "outcome", "ticket", "host", "provider",
                "model_requested", "model_host", "agent_type", "label")


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def read_jsonl(path):
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue                      # a torn last line must not hide the rest
    return out


def append(path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def count(v):
    """A token count as the host gave it: an int, or None when it is absent or not a number."""
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def agent_key(run_id, agent_id):
    return f"{run_id}/{agent_id}"


# ---------------------------------------------------------------- normalising one host's counts
def anthropic_tokens(u):
    """Anthropic reports the four categories apart: input excludes both cache counts."""
    u = u or {}
    return {"input": count(u.get("input_tokens")), "output": count(u.get("output_tokens")),
            "cache_read": count(u.get("cache_read_input_tokens")),
            "cache_write": count(u.get("cache_creation_input_tokens")),
            "output_reasoning": count((u.get("output_tokens_details") or {}).get("thinking_tokens"))}


def openai_tokens(u):
    """Codex reports input_tokens with the cached part inside it (the CLI's own 'tokens used' line
    is input - cached + output), so the uncached input is the difference. cache_write is taken as
    reported and not subtracted: it was 0 in every observed run, so its relation to input_tokens
    is not established. A key the CLI did not send stays unavailable."""
    u = u or {}
    raw_in, cached = count(u.get("input_tokens")), count(u.get("cached_input_tokens"))
    if raw_in is None:
        fresh = None
    elif cached is None:
        fresh = None                     # cannot split cached from uncached: say so, do not guess
    else:
        fresh = max(raw_in - cached, 0)
    return {"input": fresh, "output": count(u.get("output_tokens")), "cache_read": cached,
            "cache_write": count(u.get("cache_write_input_tokens")),
            "output_reasoning": count(u.get("reasoning_output_tokens"))}


def base(kind, source, provider, host, run_id, agent_id):
    return {"schema_version": 1, "kind": kind, "ingested": now(), "source": source,
            "provider": provider, "host": host, "run_id": run_id, "agent_id": agent_id}


def observed(run_id, agent_id, **fields):
    return {"schema_version": 1, "at": now(), "basis": "observed", "run_id": run_id,
            "agent_id": agent_id, **{k: v for k, v in fields.items() if v is not None}}


# ---------------------------------------------------------------- adapters
def lines_of(path):
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            yield json.loads(line)
        except Exception:
            continue


def tool_use_ids(message):
    c = message.get("content")
    return [b.get("id") for b in c if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id")] \
        if isinstance(c, list) else []


def parse_claude_stream(path, run_id=None):
    """The live event stream of a headless run. Assistant events are snapshots taken when a
    content block arrives (stop_reason is null), so their output count is partial; the result
    events carry the host's exact totals for the main loop and, cumulatively, for the whole run."""
    records, agents = [], []
    rid = run_id
    spawned_by = {}                       # tool_use id -> the agent that issued it
    task_of = {}                          # tool_use id -> the subagent it started
    known = set()
    failed = False
    saw_result = False
    for o in lines_of(path):
        t, sub = o.get("type"), o.get("subtype")
        rid = rid or o.get("session_id")
        if t == "system" and sub == "init":
            if MAIN not in known:
                known.add(MAIN)
                agents.append(observed(rid, MAIN, host="claude-code", provider="anthropic",
                                       model_host=o.get("model")))
        elif t == "assistant" and isinstance(o.get("message"), dict):
            m = o["message"]
            via = o.get("parent_tool_use_id")
            aid = o.get("agent_id") or (MAIN if not via else task_of.get(via) or "tool:" + via)
            for tu in tool_use_ids(m):
                spawned_by[tu] = aid
            if m.get("model") == "<synthetic>" or not m.get("id"):
                continue                  # a host placeholder, not a provider response
            if aid != MAIN and aid not in known:
                known.add(aid)
                agents.append(observed(rid, aid, parent=agent_key(rid, spawned_by.get(via, MAIN)),
                                       host="claude-code", provider="anthropic"))
            r = base("response", "claude-stream", "anthropic", "claude-code", rid, aid)
            r.update(response_id=m["id"], response_id_source="provider", request_id=o.get("request_id"),
                     at=o.get("timestamp"), model_reported=m.get("model"),
                     final=m.get("stop_reason") is not None, tokens=anthropic_tokens(m.get("usage")))
            records.append(r)
        elif t == "system" and sub == "task_started" and o.get("task_id"):
            parent = spawned_by.get(o.get("tool_use_id"), MAIN)
            if o.get("tool_use_id"):
                task_of[o["tool_use_id"]] = o["task_id"]
            known.add(o["task_id"])
            agents.append(observed(rid, o["task_id"], parent=agent_key(rid, parent),
                                   agent_type=o.get("subagent_type"), host="claude-code", provider="anthropic"))
        elif t == "system" and sub == "task_notification" and o.get("task_id"):
            agents.append(observed(rid, o["task_id"], outcome=o.get("status")))
            total = count((o.get("usage") or {}).get("total_tokens"))
            if total is not None:
                r = base("host_total", "claude-stream", "anthropic", "claude-code", rid, o["task_id"])
                r.update(scope="agent_sum", key="task_notification", total_tokens=total)
                records.append(r)
        elif t == "result":
            saw_result = True
            failed = failed or bool(o.get("is_error")) or (sub not in (None, "success"))
            r = base("host_total", "claude-stream", "anthropic", "claude-code", rid, MAIN)
            r.update(scope="agent", key=o.get("uuid") or f"result-{len(records)}",
                     tokens=anthropic_tokens(o.get("usage")))
            records.append(r)
            mu = o.get("modelUsage")
            if isinstance(mu, dict) and mu:
                tot = {c: 0 for c in CATEGORIES}
                for v in mu.values():
                    for c, k in (("input", "inputTokens"), ("output", "outputTokens"),
                                 ("cache_read", "cacheReadInputTokens"),
                                 ("cache_write", "cacheCreationInputTokens")):
                        n = count((v or {}).get(k))
                        tot[c] = None if (n is None or tot[c] is None) else tot[c] + n
                r = base("host_total", "claude-stream", "anthropic", "claude-code", rid, None)
                r.update(scope="run", key="modelUsage", cumulative=True, tokens=tot, models=sorted(mu))
                records.append(r)
    if rid and saw_result:
        agents.append(observed(rid, MAIN, outcome="failed" if failed else "completed"))
    for row in records + agents:
        row["run_id"] = rid
    return rid, records, agents


def parse_claude_transcript(path, run_id=None):
    """A saved session file: one line per content block, each repeating the response's usage.
    Subagent files live in <session>/subagents/agent-<id>.jsonl with a .meta.json beside each."""
    path = Path(path)
    records, agents = [], []
    rid = run_id
    spawned_by = {}

    def read(file, forced_agent=None):
        nonlocal rid
        for o in lines_of(file):
            if o.get("type") != "assistant" or not isinstance(o.get("message"), dict):
                continue
            m = o["message"]
            rid = rid or o.get("sessionId")
            aid = forced_agent or (o.get("agentId") if o.get("isSidechain") else MAIN) or MAIN
            for tu in tool_use_ids(m):
                spawned_by[tu] = aid
            if m.get("model") == "<synthetic>" or not m.get("id") or not isinstance(m.get("usage"), dict):
                continue
            r = base("response", "claude-transcript", "anthropic", "claude-code", rid, aid)
            r.update(response_id=m["id"], response_id_source="provider", request_id=o.get("requestId"),
                     at=o.get("timestamp"), model_reported=m.get("model"),
                     final=m.get("stop_reason") is not None, tokens=anthropic_tokens(m.get("usage")))
            records.append(r)

    read(path)
    if rid:
        agents.append(observed(rid, MAIN, host="claude-code", provider="anthropic"))
    sub = path.with_suffix("") / "subagents"
    if sub.is_dir():
        for f in sorted(sub.glob("agent-*.jsonl")):
            aid = f.stem[len("agent-"):]
            read(f, forced_agent=aid)
            meta = {}
            mp = f.with_name(f.stem + ".meta.json")
            if mp.is_file():
                try:
                    meta = json.loads(mp.read_text(encoding="utf-8"))
                except Exception:
                    meta = {}
            parent = spawned_by.get(meta.get("toolUseId"), MAIN)
            agents.append(observed(rid, aid, parent=agent_key(rid, parent), agent_type=meta.get("agentType"),
                                   model_host=meta.get("model"), host="claude-code", provider="anthropic"))
    for row in records + agents:
        row["run_id"] = rid
    return rid, records, agents


def parse_codex_events(path, run_id=None):
    """`codex exec --json`: one usage object per finished turn, no response id and no model.
    The turn totals are host totals for this thread; they stand in only when the session file
    (which has the response ids) was not ingested."""
    records, agents = [], []
    rid, turn, done, failed = run_id, 0, False, False
    for o in lines_of(path):
        t = o.get("type")
        if t == "thread.started":
            rid = rid or o.get("thread_id")
        elif t == "turn.completed":
            turn += 1
            done = True
            r = base("host_total", "codex-events", "openai", "codex", rid, MAIN)
            r.update(scope="agent", key=f"turn-{turn}", tokens=openai_tokens(o.get("usage")))
            records.append(r)
        elif t in ("turn.failed", "error"):
            failed = True
    if rid:
        agents.append(observed(rid, MAIN, host="codex", provider="openai",
                               outcome="failed" if failed else "completed" if done else None))
    for row in records + agents:
        row["run_id"] = rid
    return rid, records, agents


def parse_codex_session(path, run_id=None):
    """A saved Codex session: token_usage_record lines carry the provider's response id. The
    model in turn_context is the one the client applied, not one the provider echoed back."""
    records, agents = [], []
    rid, model_host, done = run_id, None, False
    for o in lines_of(path):
        t, p = o.get("type"), o.get("payload") if isinstance(o.get("payload"), dict) else {}
        if t == "session_meta":
            rid = rid or p.get("id") or p.get("session_id")
        elif t == "turn_context":
            model_host = p.get("model") or model_host
        elif t == "token_usage_record":
            rid = rid or p.get("thread_id")
            resp = p.get("response_id")
            r = base("response", "codex-session", "openai", "codex", rid, MAIN)
            r.update(response_id=resp or f"{p.get('turn_id')}#{len(records)}",
                     response_id_source="provider" if resp else "synthesized:turn+position",
                     request_id=None, at=o.get("timestamp"), model_reported=None, turn_id=p.get("turn_id"),
                     final=True, tokens=openai_tokens(p.get("usage")))
            records.append(r)
        elif t == "event_msg" and p.get("type") == "task_complete":
            done = True
    if rid:
        agents.append(observed(rid, MAIN, host="codex", provider="openai", model_host=model_host,
                               outcome="completed" if done else None))
    for row in records + agents:
        row["run_id"] = rid
    return rid, records, agents


PARSERS = {"claude-stream": parse_claude_stream, "claude-transcript": parse_claude_transcript,
           "codex-events": parse_codex_events, "codex-session": parse_codex_session}


def ingest(fmt, path, run_id=None):
    """Parse and append. Returns the run id and what was written. Ingesting the same file twice
    appends the same records again; the report counts each response once."""
    rid, records, agents = PARSERS[fmt](path, run_id)
    if not rid:
        raise SystemExit(f"usage: no run id in {path}; pass --run-id")
    append(RECORDS, records)
    append(AGENTS, agents)
    return rid, records, agents


def declare(run_id, agent_id=MAIN, **fields):
    row = {"schema_version": 1, "at": now(), "basis": "declared", "run_id": run_id, "agent_id": agent_id,
           **{k: v for k, v in fields.items() if k in AGENT_FIELDS and v is not None}}
    append(AGENTS, [row])
    return row


# ---------------------------------------------------------------- deduplication
def merge_tokens(a, b):
    out = {}
    for c in CATEGORIES + EXTRA:
        x, y = a.get(c), b.get(c)
        out[c] = y if x is None else x if y is None else max(x, y)
    return out


def dedupe(rows):
    """Responses by (provider, run, response id); host totals by (run, scope, agent, key)."""
    responses, totals, seen = {}, {}, 0
    for r in rows:
        if r.get("kind") == "response":
            seen += 1
            k = (r.get("provider"), r.get("run_id"), r.get("response_id"))
            old = responses.get(k)
            if old is None:
                responses[k] = dict(r, sources=[r.get("source")], lines=1)
                continue
            if r.get("final") and not old.get("final"):
                tokens = dict(r["tokens"])                  # the final count replaces the snapshot
            elif old.get("final") and not r.get("final"):
                tokens = dict(old["tokens"])
            else:
                tokens = merge_tokens(old["tokens"], r["tokens"])
            keep = r if (r.get("final") and not old.get("final")) else old
            merged = dict(keep, tokens=tokens, final=bool(old.get("final") or r.get("final")),
                          model_reported=old.get("model_reported") or r.get("model_reported"),
                          sources=sorted(set(old["sources"]) | {r.get("source")}), lines=old["lines"] + 1)
            responses[k] = merged
        elif r.get("kind") == "host_total":
            k = (r.get("run_id"), r.get("scope"), r.get("agent_id"), r.get("key"))
            old = totals.get(k)
            if old is None:
                totals[k] = dict(r)
            elif r.get("scope") == "agent_sum":
                totals[k]["total_tokens"] = max(old.get("total_tokens") or 0, r.get("total_tokens") or 0)
            else:
                totals[k]["tokens"] = merge_tokens(old["tokens"], r["tokens"])
    return list(responses.values()), list(totals.values()), seen


def agent_table(run_filter=None):
    """Latest value per field; a declared value outranks an observed one."""
    table = {}
    for row in read_jsonl(AGENTS):
        if run_filter and row.get("run_id") not in run_filter:
            continue
        k = agent_key(row.get("run_id"), row.get("agent_id"))
        a = table.setdefault(k, {"run_id": row.get("run_id"), "agent_id": row.get("agent_id"),
                                 "_basis": {}})
        for f in AGENT_FIELDS:
            if row.get(f) is None:
                continue
            if a["_basis"].get(f) == "declared" and row.get("basis") != "declared":
                continue
            a[f] = row[f]
            a["_basis"][f] = row.get("basis")
    return table


# ---------------------------------------------------------------- figures
def total_of(values, lower_bound=False):
    """A figure over a set of values that may be unavailable. sum is null when nothing is known."""
    known = [v for v in values if v is not None]
    return {"sum": sum(known) if known else None, "known": len(known),
            "unavailable": len(values) - len(known), "lower_bound": bool(lower_bound and known)}


def figures(rows, flags=None):
    """rows: token dicts. flags: per row, True where the output count is only a lower bound."""
    flags = flags or [False] * len(rows)
    out = {}
    for c in CATEGORIES + EXTRA:
        out[c] = total_of([r.get(c) for r in rows],
                          lower_bound=(c == "output" and any(f and r.get("output") is not None
                                                             for f, r in zip(flags, rows))))
    whole = [None if any(r.get(c) is None for c in CATEGORIES) else sum(r[c] for c in CATEGORIES) for r in rows]
    out["total"] = total_of(whole, lower_bound=any(f and w is not None for f, w in zip(flags, whole)))
    return out


def averages(procs):
    """Per process: the mean over the processes that have the value; the rest are counted apart."""
    out = {}
    for c in CATEGORIES + ("total",):
        vals = [p["tokens"].get(c) for p in procs]
        known = [v for v in vals if v is not None]
        out[c] = {"mean": round(sum(known) / len(known), 1) if known else None, "processes": len(known),
                  "unavailable": len(vals) - len(known),
                  "lower_bound": any(p.get("output_lower_bound") for p in procs
                                     if c in ("output", "total") and p["tokens"].get(c) is not None)}
    return out


def coordinator_view(ticket):
    """Role, stage and outcome from the workflow ledger, read only. None when it cannot be read."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import coordinator as co
        if not co.ticket_path(ticket):
            return None
        t, st = co.load_ticket(ticket), co.state_of(ticket)
        return {"stage": t.get("kind"), "role": st.get("worker"),
                "outcome": st["state"] if st["state"] in co.TERMINAL else None}
    except BaseException:
        return None


def build_report(run_ids=None):
    rows = read_jsonl(RECORDS)
    if run_ids:
        rows = [r for r in rows if r.get("run_id") in run_ids]
    responses, host_totals, seen = dedupe(rows)
    table = agent_table(set(run_ids) if run_ids else None)
    for r in responses:                                    # an agent seen only through its responses
        table.setdefault(agent_key(r["run_id"], r["agent_id"]),
                         {"run_id": r["run_id"], "agent_id": r["agent_id"], "_basis": {}})
    for h in host_totals:
        if h.get("agent_id"):
            table.setdefault(agent_key(h["run_id"], h["agent_id"]),
                             {"run_id": h["run_id"], "agent_id": h["agent_id"], "_basis": {}})

    processes, unknowns = [], []
    for key in sorted(table):
        a = table[key]
        rs = [r for r in responses if agent_key(r["run_id"], r["agent_id"]) == key]
        turn_totals = [h for h in host_totals if h.get("scope") == "agent"
                       and agent_key(h["run_id"], h["agent_id"]) == key]
        if rs and all(r.get("final") for r in rs):
            basis, parts, lower = "responses", [r["tokens"] for r in rs], False
        elif turn_totals:
            basis, parts, lower = "host_turn_totals", [h["tokens"] for h in turn_totals], False
        elif rs:
            basis, parts, lower = "responses_partial", [r["tokens"] for r in rs], True
        else:
            basis, parts, lower = "unavailable", [], False
        tokens = {}
        for c in CATEGORIES + EXTRA:
            vals = [p.get(c) for p in parts]
            tokens[c] = sum(vals) if vals and all(v is not None for v in vals) else None
        tokens["total"] = (sum(tokens[c] for c in CATEGORIES)
                           if all(tokens[c] is not None for c in CATEGORIES) else None)
        led = coordinator_view(a["ticket"]) if a.get("ticket") else None
        role = a.get("role") or (led or {}).get("role") or a.get("agent_type")
        role_basis = ("declared" if a.get("role") else "ticket" if (led or {}).get("role")
                      else "observed:agent_type" if a.get("agent_type") else None)
        stage = a.get("stage") or (led or {}).get("stage")
        outcome = a.get("outcome") if a["_basis"].get("outcome") == "declared" else \
            ((led or {}).get("outcome") or a.get("outcome"))
        models = sorted({r["model_reported"] for r in rs if r.get("model_reported")})
        p = {"process": key, "run_id": a["run_id"], "agent_id": a["agent_id"], "parent": a.get("parent"),
             "relation": "child" if a.get("parent") else "parent",
             "role": role or UNKNOWN, "role_basis": role_basis, "stage": stage or UNKNOWN,
             "outcome": outcome or UNKNOWN, "ticket": a.get("ticket"), "host": a.get("host"),
             "provider": a.get("provider"), "model_requested": a.get("model_requested"),
             "model_host": a.get("model_host"), "models_reported": models,
             "responses": len(rs), "response_lines": sum(r["lines"] for r in rs),
             "basis": basis, "output_lower_bound": lower and tokens.get("output") is not None,
             "tokens": tokens}
        processes.append(p)
        for c in CATEGORIES:
            if tokens[c] is None:
                unknowns.append({"process": key, "field": f"tokens.{c}",
                                 "why": "no record for this process" if basis == "unavailable"
                                 else "the host did not report this count for every response"})
        if lower and tokens.get("output") is not None:
            unknowns.append({"process": key, "field": "tokens.output",
                             "why": "only live snapshots were ingested; the count is a lower bound. "
                                    "Ingest the saved session file for the final count."})
        if not models:
            unknowns.append({"process": key, "field": "model_reported",
                             "why": "this host's capture carries no model field from the provider"})
        for f, v in (("role", role), ("stage", stage), ("outcome", outcome)):
            if not v:
                unknowns.append({"process": key, "field": f, "why": "not declared and not observable"})

    def group(procs):
        return {"processes": len(procs),
                "tokens": figures([p["tokens"] for p in procs], [p["output_lower_bound"] for p in procs])}

    def by(field):
        names = sorted({p[field] for p in processes})
        return {n: group([p for p in processes if p[field] == n]) for n in names}

    parents = [p for p in processes if p["relation"] == "parent"]
    children = [p for p in processes if p["relation"] == "child"]

    def compare(got, want, partial):
        if got is None or want is None:
            return "unavailable"
        if got == want:
            return "reconciled"
        return "below host total (partial snapshots)" if (partial and got < want) else "differs"

    runs = []
    for rid in sorted({p["run_id"] for p in processes}):
        procs = [p for p in processes if p["run_id"] == rid]
        partial = any(p["output_lower_bound"] for p in procs)
        checks = []
        # the whole run against the host's cumulative total
        run_total = next((h for h in host_totals if h.get("scope") == "run" and h["run_id"] == rid), None)
        if run_total:
            cats = {}
            for c in CATEGORIES:
                mine = [p["tokens"][c] for p in procs]
                got = sum(mine) if all(v is not None for v in mine) else None
                want = run_total["tokens"].get(c)
                cats[c] = {"accounted": got, "host": want, "verdict": compare(got, want, partial and c == "output")}
            checks.append({"scope": "run", "against": "host run total", "by_category": cats})
        # one agent's responses against the host's totals for that agent
        for p in procs:
            mine_totals = [h for h in host_totals if h.get("scope") == "agent"
                           and h["run_id"] == rid and h["agent_id"] == p["agent_id"]]
            if mine_totals and p["basis"] in ("responses", "responses_partial"):
                cats = {}
                for c in CATEGORIES:
                    vals = [h["tokens"].get(c) for h in mine_totals]
                    want = sum(vals) if all(v is not None for v in vals) else None
                    cats[c] = {"accounted": p["tokens"][c], "host": want,
                               "verdict": compare(p["tokens"][c], want, p["output_lower_bound"] and c == "output")}
                checks.append({"scope": "agent", "agent_id": p["agent_id"],
                               "against": "host turn totals", "by_category": cats})
            agent_sum = next((h.get("total_tokens") for h in host_totals if h.get("scope") == "agent_sum"
                              and h["run_id"] == rid and h["agent_id"] == p["agent_id"]), None)
            if agent_sum is not None:
                checks.append({"scope": "agent", "agent_id": p["agent_id"], "against": "host agent token sum",
                               "by_category": {"total": {
                                   "accounted": p["tokens"]["total"], "host": agent_sum,
                                   "verdict": compare(p["tokens"]["total"], agent_sum, p["output_lower_bound"])}}})
        verdicts = {v["verdict"] for ch in checks for v in ch["by_category"].values()}
        runs.append({"run_id": rid, "processes": len(procs),
                     "responses": sum(p["responses"] for p in procs),
                     "duplicate_lines_dropped": sum(p["response_lines"] - p["responses"] for p in procs),
                     "checks": checks,
                     "verdict": ("no host total to check against" if not checks else
                                 "differs" if "differs" in verdicts else
                                 "reconciled" if verdicts == {"reconciled"} else "partly checked")})

    return {"generated": now(), "store": str(USAGE), "runs_filter": sorted(run_ids) if run_ids else None,
            "response_lines_read": seen, "responses_counted": len(responses),
            "processes": processes,
            "totals": {"all": group(processes), "parent": group(parents), "child": group(children)},
            "by_role": by("role"), "by_stage": by("stage"), "by_outcome": by("outcome"),
            "averages_per_process": {"all": averages(processes), "parent": averages(parents),
                                     "child": averages(children)},
            "runs": runs, "unknown": unknowns}


# ---------------------------------------------------------------- printing
def cell(v, lower=False):
    return "n/a" if v is None else (">=" if lower else "") + f"{v:,}"


def print_report(rep):
    print(f"usage report  {rep['generated']}  store {rep['store']}")
    print(f"{rep['response_lines_read']} response lines read, {rep['responses_counted']} responses counted "
          f"(each provider response once per run)")
    if not rep["processes"]:
        print("no usage recorded")
        return
    print()
    print(f"{'process':34s} {'rel':6s} {'role':18s} {'stage':11s} {'outcome':10s} "
          f"{'input':>9s} {'output':>9s} {'cache_rd':>10s} {'cache_wr':>10s}  basis")
    for p in rep["processes"]:
        t = p["tokens"]
        name = p["process"] if len(p["process"]) <= 34 else f"{p['run_id'][:13]}~/{p['agent_id']}"[:34]
        print(f"{name:34s} {p['relation']:6s} {p['role'][:18]:18s} {p['stage'][:11]:11s} "
              f"{p['outcome'][:10]:10s} {cell(t['input']):>9s} {cell(t['output'], p['output_lower_bound']):>9s} "
              f"{cell(t['cache_read']):>10s} {cell(t['cache_write']):>10s}  {p['basis']}")

    def line(name, g):
        t = g["tokens"]
        gaps = sum(t[c]["unavailable"] for c in CATEGORIES)
        print(f"  {name[:22]:22s} n={g['processes']:<3d} input {cell(t['input']['sum']):>9s}  "
              f"output {cell(t['output']['sum'], t['output']['lower_bound']):>9s}  "
              f"cache_read {cell(t['cache_read']['sum']):>10s}  cache_write {cell(t['cache_write']['sum']):>10s}"
              + (f"  ({gaps} value(s) unavailable)" if gaps else ""))

    print("\ntotals")
    for name in ("all", "parent", "child"):
        line(name, rep["totals"][name])
    for title, key in (("by role", "by_role"), ("by stage", "by_stage"), ("by outcome", "by_outcome")):
        print(title)
        for name, g in rep[key].items():
            line(name, g)
    print("average per process")
    for name in ("all", "parent", "child"):
        a = rep["averages_per_process"][name]
        print(f"  {name:22s} " + "  ".join(
            f"{c} {('n/a' if a[c]['mean'] is None else ('>=' if a[c]['lower_bound'] else '') + format(a[c]['mean'], ',.1f'))}"
            f" (n={a[c]['processes']}" + (f", {a[c]['unavailable']} n/a" if a[c]["unavailable"] else "") + ")"
            for c in CATEGORIES))
    print("checks against the host's own totals")
    for r in rep["runs"]:
        print(f"  {r['run_id']}: {r['verdict']}; {r['responses']} responses, "
              f"{r['duplicate_lines_dropped']} duplicate line(s) dropped")
        for ch in r["checks"]:
            for c, v in ch["by_category"].items():
                if v["verdict"] != "reconciled":
                    who = ch.get("agent_id") or "run"
                    print(f"    {who} {c} against {ch['against']}: accounted {cell(v['accounted'])}, "
                          f"host {cell(v['host'])}: {v['verdict']}")
    if rep["unknown"]:
        print(f"unknown ({len(rep['unknown'])})")
        for u in rep["unknown"]:
            print(f"  {u['process']}  {u['field']}: {u['why']}")


# ---------------------------------------------------------------- commands
def cmd_ingest(a):
    rid, records, agents = ingest(a.format, a.file, a.run_id)
    fields = {k: getattr(a, k) for k in AGENT_FIELDS if getattr(a, k, None) is not None}
    if fields:
        declare(rid, a.agent, **fields)
    print(json.dumps({"run_id": rid, "format": a.format,
                      "responses": sum(1 for r in records if r["kind"] == "response"),
                      "host_totals": sum(1 for r in records if r["kind"] == "host_total"),
                      "agents_observed": sorted({x["agent_id"] for x in agents if x.get("agent_id")}),
                      "declared": fields or None, "store": str(USAGE)}, ensure_ascii=False, indent=1))
    return 0


def cmd_declare(a):
    fields = {k: getattr(a, k) for k in AGENT_FIELDS if getattr(a, k, None) is not None}
    if not fields:
        raise SystemExit("usage: declare needs at least one field")
    print(json.dumps(declare(a.run, a.agent, **fields), ensure_ascii=False, indent=1))
    return 0


def cmd_report(a):
    rep = build_report(a.run or None)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print_report(rep)
    return 0


def cmd_show(a):
    rows = [r for r in read_jsonl(RECORDS) if r.get("run_id") == a.run]
    responses, host_totals, seen = dedupe(rows)
    print(json.dumps({"run_id": a.run, "response_lines": seen, "responses": responses,
                      "host_totals": host_totals}, ensure_ascii=False, indent=1))
    return 0


def add_agent_fields(p):
    p.add_argument("--agent", default=MAIN, help="agent within the run (default: main)")
    p.add_argument("--parent", help="the process that started this one: <run id>/<agent id>")
    p.add_argument("--role"); p.add_argument("--stage"); p.add_argument("--outcome")
    p.add_argument("--ticket", help="a Coordinator ticket: stage, role and outcome are read from the ledger")
    p.add_argument("--host"); p.add_argument("--provider")
    p.add_argument("--model-requested", dest="model_requested")
    p.add_argument("--model-host", dest="model_host"); p.add_argument("--agent-type", dest="agent_type")
    p.add_argument("--label")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("ingest")
    i.add_argument("--format", required=True, choices=FORMATS); i.add_argument("file")
    i.add_argument("--run-id", dest="run_id", default=None)
    add_agent_fields(i); i.set_defaults(func=cmd_ingest)
    d = sub.add_parser("declare"); d.add_argument("--run", required=True)
    add_agent_fields(d); d.set_defaults(func=cmd_declare)
    r = sub.add_parser("report"); r.add_argument("--run", action="append"); r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_report)
    s = sub.add_parser("show"); s.add_argument("--run", required=True); s.set_defaults(func=cmd_show)
    a = ap.parse_args()
    raise SystemExit(a.func(a))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
