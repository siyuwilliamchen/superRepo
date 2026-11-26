"""Requested model against the model actually reported, for one tiny worker on one host.

A role text names a model, a host is asked for it, and something answers. This tool runs the
smallest possible worker (one fixed sentence in, two letters out, no tools, an empty scratch
directory), reads what the host and the provider said about the model, and records the
comparison. Anything it could not read is written down as unknown, with the reason; nothing
is filled in from the request. Method and observed results: system/methods/usage.md.

  run       start one tiny worker and record the comparison (uses the provider: costs a few tokens)
              --host claude --model haiku
              --host codex  --model gpt-5.6-luna
  evaluate  the same comparison from a saved capture, no worker started (used by the tests)
  choices   the model choices this host advertises, where it advertises any
  list      the comparisons recorded so far

Three names are kept apart, because they can differ:

  requested          what this tool asked the host for
  host_resolved      what the host says it selected (an alias expanded, a setting applied)
  provider_reported  the model field in the provider's own response

Verdicts: match (exact id asked, same id reported), match_with_suffix (reported id is the asked
id plus a suffix such as a date), alias_resolved (an alias was asked; the reported id names that
family), mismatch, mixed (several models answered one run), unknown (no provider-reported model
could be read; host_resolved is then all there is, and it is not the provider's word).

Permissions of the worker: Claude runs with no built-in tools, no MCP servers, safe mode (no
hooks, skills, plugins or project instructions), prompts denied, session not saved. Codex runs
read-only, without the user's config or rules, session not saved unless --persist. Both run in a
new empty directory that is deleted afterwards. Records go to .local/usage/ (git-ignored).
"""
from pathlib import Path
import argparse, datetime as dt, json, os, shutil, subprocess, sys, tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))   # python -I drops the script dir
import usage                                                 # noqa: E402

ROOT = usage.ROOT
CHECKS = usage.USAGE / "model-checks.jsonl"
RAW = usage.USAGE / "raw"
PROMPT = "Reply with exactly the two letters: ok"
HOSTS = {"claude": {"host": "claude-code", "provider": "anthropic"},
         "codex": {"host": "codex", "provider": "openai"}}
CLAUDE_FLAGS = ["--output-format", "stream-json", "--verbose", "--tools", "", "--strict-mcp-config",
                "--permission-prompts", "none", "--safe-mode", "--no-session-persistence"]
CODEX_FLAGS = ["--json", "--sandbox", "read-only", "--skip-git-repo-check", "--ignore-user-config",
               "--ignore-rules"]

now = usage.now


def codex_home():
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def request_kind(host, requested):
    """An alias is a bare family word (haiku, sonnet); anything with a version in it is an id."""
    bare = requested.replace("_", "").isalpha()
    return "alias" if (host == "claude" and bare) else "exact"


def advertised(host):
    """(choices or None, where they came from). None means the host advertises no list here."""
    if host == "codex":
        p = codex_home() / "models_cache.json"
        try:
            models = json.loads(p.read_text(encoding="utf-8")).get("models") or []
            slugs = [m["slug"] for m in models if isinstance(m, dict) and m.get("slug")]
            return (slugs or None), f"{p.name} in the Codex home directory"
        except Exception as e:
            return None, f"the Codex model cache could not be read ({type(e).__name__})"
    return None, ("the claude CLI prints no model list; its help names the aliases fable, opus and "
                  "sonnet, and a choice is shown to be supported only by the host running it")


def argv_for(host, model, exe, persist=False):
    if host == "claude":
        return [exe, "-p", PROMPT, "--model", model, *CLAUDE_FLAGS]
    return [exe, "exec", "-m", model, *CODEX_FLAGS, *([] if persist else ["--ephemeral"]), PROMPT]


def find_codex_session(thread_id):
    if not thread_id:
        return None
    hits = sorted((codex_home() / "sessions").glob(f"**/rollout-*{thread_id}.jsonl"))
    return hits[-1] if hits else None


def verdict_of(requested, kind, reported):
    if not reported:
        return "unknown"
    if len(reported) > 1:
        return "mixed"
    got = reported[0]
    if kind == "alias":
        return "alias_resolved" if requested.lower() in got.lower() else "mismatch"
    if got == requested:
        return "match"
    return "match_with_suffix" if got.startswith(requested + "-") else "mismatch"


def evaluate(host, requested, capture, session_file=None, exit_code=None, supported=None,
             supported_basis=None):
    """Read one capture and say what is known. Pure: starts nothing, writes nothing."""
    ident = HOSTS[host]
    kind = request_kind(host, requested)
    unknown, host_resolved, host_src, reported, rep_src, accounted = [], None, None, [], None, None
    run_id, responses, error = None, 0, None

    if host == "claude":
        for o in usage.lines_of(capture):
            t = o.get("type")
            run_id = run_id or o.get("session_id")
            if t == "system" and o.get("subtype") == "init" and o.get("model"):
                host_resolved, host_src = o["model"], "stream system/init .model"
            elif t == "assistant" and isinstance(o.get("message"), dict):
                m = o["message"]
                if m.get("model") and m.get("model") != "<synthetic>" and m.get("id"):
                    responses += 1
                    if m["model"] not in reported:
                        reported.append(m["model"])
            elif t == "result":
                if isinstance(o.get("modelUsage"), dict):
                    accounted = sorted(o["modelUsage"])
                if o.get("is_error"):
                    error = str(o.get("subtype") or o.get("api_error_status") or "error")
        rep_src = f"assistant message.model in {responses} provider response(s)" if reported else None
        if not reported:
            unknown.append({"field": "provider_reported",
                            "why": "the capture holds no provider response"
                                   + (f" (the run ended with: {error})" if error else "")})
        if not host_resolved:
            unknown.append({"field": "host_resolved", "why": "no system/init event in the capture"})
    else:
        for o in usage.lines_of(capture):
            if o.get("type") == "thread.started":
                run_id = run_id or o.get("thread_id")
            if o.get("type") in ("turn.failed", "error"):
                error = str(o.get("message") or (o.get("error") or {}).get("message") or o.get("type"))[:200]
            if isinstance(o.get("model"), str) and o["model"] not in reported:
                reported.append(o["model"])            # no observed CLI version sends this; read it if one does
        rep_src = "a model field in the exec event stream" if reported else None
        if session_file:
            for o in usage.lines_of(session_file):
                p = o.get("payload") if isinstance(o.get("payload"), dict) else {}
                if o.get("type") == "turn_context" and p.get("model"):
                    host_resolved, host_src = p["model"], "session file turn_context .model (applied by the client)"
        if not reported:
            unknown.append({"field": "provider_reported",
                            "why": "codex exec --json carries no model field, and the session file holds only "
                                   "the model the client applied; nothing read here is the provider's own "
                                   "statement of which model answered"})
        if not host_resolved:
            unknown.append({"field": "host_resolved",
                            "why": "the exec event stream names no model; run with --persist to read the "
                                   "client-applied model from the session file" if not session_file
                            else "the session file holds no turn_context model"})
        accounted = None
        unknown.append({"field": "host_accounted",
                        "why": "Codex reports usage per turn without naming a model"})

    if supported is None and host_resolved and exit_code == 0 and not error:
        supported, supported_basis = True, "the host accepted the choice and ran it"
    if supported is None:
        unknown.append({"field": "host_supported", "why": supported_basis or "not checked"})
    if run_id is None:
        unknown.append({"field": "run_id", "why": "the capture names no session or thread"})
    verdict = verdict_of(requested, kind, reported)
    agrees = None
    if host_resolved:
        agrees = (requested.lower() in host_resolved.lower()) if kind == "alias" else host_resolved == requested
    return {"schema_version": 1, "at": now(), **ident, "requested": requested, "requested_kind": kind,
            "host_supported": supported, "host_supported_basis": supported_basis,
            "host_resolved": host_resolved, "host_resolved_source": host_src,
            "host_resolved_agrees_with_request": agrees,
            "provider_reported": reported, "provider_reported_source": rep_src,
            "host_accounted": accounted, "responses": responses or None,
            "verdict": verdict, "unknown": unknown, "run_id": run_id, "exit_code": exit_code, "error": error}


def cli_version(exe):
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8", timeout=30)
        return r.stdout.strip().splitlines()[0] if r.returncode == 0 and r.stdout.strip() else None
    except Exception:
        return None


def record(rec):
    usage.append(CHECKS, [rec])
    return rec


def run(host, model, timeout=240, persist=False, keep_raw=False, force=False, role="probe"):
    choices, basis = advertised(host)
    supported = None if choices is None else model in choices
    if supported is False and not force:
        raise SystemExit(f"modelcheck: {model} is not among the choices {host} advertises "
                         f"({', '.join(choices)}); use --force to ask anyway")
    exe = shutil.which(host)
    if not exe:
        rec = {"schema_version": 1, "at": now(), **HOSTS[host], "requested": model,
               "requested_kind": request_kind(host, model), "host_supported": supported,
               "host_supported_basis": basis, "host_resolved": None, "provider_reported": [],
               "verdict": "unknown", "run_id": None, "exit_code": None,
               "unknown": [{"field": "everything", "why": f"the {host} command is not on PATH; no worker ran"}]}
        return record(rec)
    argv = argv_for(host, model, exe, persist)
    scratch = Path(tempfile.mkdtemp(prefix="liveos-modelcheck-"))
    capture = scratch / "capture.jsonl"
    error = None
    try:
        with capture.open("wb") as out:
            try:
                p = subprocess.run(argv, cwd=str(scratch), stdin=subprocess.DEVNULL, stdout=out,
                                   stderr=subprocess.PIPE, timeout=timeout)
                code = p.returncode
                if code != 0:
                    error = (p.stderr or b"").decode("utf-8", "replace").strip()[-300:] or None
            except subprocess.TimeoutExpired:
                code, error = None, f"no result within {timeout}s"
        session_file = None
        if host == "codex" and persist:
            thread = next((o.get("thread_id") for o in usage.lines_of(capture)
                           if o.get("type") == "thread.started"), None)
            session_file = find_codex_session(thread)
        rec = evaluate(host, model, capture, session_file, code,
                       supported if supported is not None else None, basis)
        if error and not rec.get("error"):
            rec["error"] = error
        rec["cli_version"] = cli_version(exe)
        rec["worker"] = {"argv": [Path(exe).name, *[a for a in argv[1:] if a != PROMPT]],
                         "prompt": PROMPT, "cwd": "a new empty directory, deleted afterwards",
                         "session_saved": bool(host == "codex" and persist)}
        # the same capture feeds the usage accounting: this is its minimal real sample
        if rec["run_id"]:
            usage.ingest("claude-stream" if host == "claude" else "codex-events", capture)
            if session_file:
                usage.ingest("codex-session", session_file)
            usage.declare(rec["run_id"], role=role, stage="modelcheck", model_requested=model,
                          label=f"modelcheck {host} {model}")
        if keep_raw:
            RAW.mkdir(parents=True, exist_ok=True)
            kept = RAW / f"{rec['run_id'] or 'no-run-id'}.{host}.jsonl"
            shutil.copy(capture, kept)
            rec["raw"] = str(kept.relative_to(ROOT)) if kept.is_relative_to(ROOT) else str(kept)
        return record(rec)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def summary_line(r):
    rep = ", ".join(r.get("provider_reported") or []) or "unknown"
    return (f"{r['at'][:19]}  {r['host']:11s} asked {r['requested']:18s} host says {str(r.get('host_resolved') or 'unknown'):18s} "
            f"provider says {rep:18s} -> {r['verdict']}"
            + (f"  [{len(r['unknown'])} unknown]" if r.get("unknown") else ""))


def cmd_run(a):
    rec = run(a.host, a.model, a.timeout, a.persist, a.keep_raw, a.force, a.role)
    print(json.dumps(rec, ensure_ascii=False, indent=1))
    return 0 if rec["verdict"] in ("match", "match_with_suffix", "alias_resolved") else \
        3 if rec["verdict"] == "unknown" else 2


def cmd_evaluate(a):
    rec = evaluate(a.host, a.model, a.capture, a.session_file, a.exit_code)
    if a.record:
        record(rec)
    print(json.dumps(rec, ensure_ascii=False, indent=1))
    return 0


def cmd_choices(a):
    choices, basis = advertised(a.host)
    print(json.dumps({"host": a.host, "choices": choices, "basis": basis}, ensure_ascii=False, indent=1))
    return 0


def cmd_list(a):
    rows = usage.read_jsonl(CHECKS)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    if not rows:
        print("no model checks recorded")
    for r in rows:
        print(summary_line(r))
        for u in r.get("unknown") or []:
            print(f"    unknown {u['field']}: {u['why']}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--host", required=True, choices=sorted(HOSTS)); r.add_argument("--model", required=True)
    r.add_argument("--timeout", type=int, default=240)
    r.add_argument("--persist", action="store_true",
                   help="codex: let the host save its session file, which holds the response ids")
    r.add_argument("--keep-raw", dest="keep_raw", action="store_true",
                   help="keep the raw capture under .local/usage/raw/ (it contains the worker's reply)")
    r.add_argument("--force", action="store_true", help="ask even if the host does not advertise the choice")
    r.add_argument("--role", default="probe")
    r.set_defaults(func=cmd_run)
    e = sub.add_parser("evaluate")
    e.add_argument("--host", required=True, choices=sorted(HOSTS)); e.add_argument("--model", required=True)
    e.add_argument("--capture", required=True); e.add_argument("--session-file", dest="session_file")
    e.add_argument("--exit-code", dest="exit_code", type=int, default=None)
    e.add_argument("--record", action="store_true")
    e.set_defaults(func=cmd_evaluate)
    c = sub.add_parser("choices"); c.add_argument("--host", required=True, choices=sorted(HOSTS))
    c.set_defaults(func=cmd_choices)
    l = sub.add_parser("list"); l.add_argument("--json", action="store_true"); l.set_defaults(func=cmd_list)
    a = ap.parse_args()
    raise SystemExit(a.func(a))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
