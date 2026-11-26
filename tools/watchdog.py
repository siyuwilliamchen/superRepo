"""The independent watchdog: watches the watchers, never writes the ledger.

Part of "LiveOS research through conversation" (William's design, 2026-11-25, section 4,
"Failure and recovery rules": an independent watchdog detects a dead worker that cannot
report itself; liveness and progress are separate; capability-specific deadlines, bounded
retries, then diagnostics). Method note: system/methods/watchdog.md.

What it is not: not the conversation, not the Coordinator service, not a worker. It is a
small process (or a scheduled task) that reads runtime state and the ledger and reports
what is dead, late, interrupted or overdue. When something must change in the ledger it
goes through the Coordinator's command line, never by writing workflow/ files itself:

  dead or late Coordinator service   -> run `coordinator.py reconcile` in its place
  ticket claimed past its deadline   -> `coordinator.py submit --kind diagnose` with a
                                        deterministic request key (one ticket per attempt,
                                        however often the watchdog runs or crashes)
  dead or late relay, interrupted or stalled run.py job
                                     -> reported with the exact command that resumes it

Deadlines per ticket kind, with their reasons in plain words: workflow/deadlines.json.
Its own heartbeat: .local/workflow/watchdog.json (runtime state, not in git).

  python tools/watchdog.py serve --once          one tick (for a scheduled task)
  python tools/watchdog.py serve [--interval N]  loop; default every 300 s
  python tools/watchdog.py status                the last tick's findings
  python tools/watchdog.py deadlines             the deadline table with reasons

An idle tick writes only its heartbeat. Exit code of `serve --once`: 0 when nothing needs
attention, 1 when something does, 2 when the tick itself failed.
"""
from pathlib import Path
import argparse, datetime as dt, json, os, subprocess, sys, time

sys.path.insert(0, str(Path(__file__).resolve().parent))   # python -I drops the script dir
import coordinator as co                                     # noqa: E402  (read-only helpers)

ROOT = co.ROOT
WORKFLOW = co.WORKFLOW
RUNTIME = co.RUNTIME
RUNS = ROOT / ".local" / "runs"
RELAYS = RUNTIME / "relays"
SESSIONS = co.SESSIONS
DEADLINES = WORKFLOW / "deadlines.json"
HEARTBEAT = RUNTIME / "watchdog.json"
LOG = RUNTIME / "watchdog.log"
COORD = Path(__file__).resolve().parent / "coordinator.py"
TOOLS_REL = "tools"

now, age, alive = co.now, co.age, co.process_alive

BUILTIN_DEADLINES = {
    "schema_version": 0,
    "kinds": {k: {"deadline_seconds": 7200, "reason": "built-in default; workflow/deadlines.json is missing"}
              for k in co.KINDS},
    "default_deadline_seconds": 7200,
    "services": {"coordinator": {"late_after_intervals": 3},
                 "relay": {"late_after_intervals": 6, "grace_seconds": 5},
                 "run": {"stale_after_seconds": 90, "stall_after_seconds": 900}},
}


def human(seconds):
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}"


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def deadlines():
    cfg = read_json(DEADLINES) if DEADLINES.is_file() else None
    if not cfg or "kinds" not in cfg:
        cfg = dict(BUILTIN_DEADLINES)
    cfg.setdefault("services", BUILTIN_DEADLINES["services"])
    cfg.setdefault("default_deadline_seconds", 7200)
    return cfg


def deadline_for(kind, cfg):
    spec = (cfg.get("kinds") or {}).get(kind) or {}
    return int(spec.get("deadline_seconds") or cfg["default_deadline_seconds"])


# ---------------------------------------------------------------- the Coordinator CLI
def coordinator(*args):
    """The only way this tool changes anything: a Coordinator command, as a new process,
    against the same root. Returns (exit code, parsed JSON or text)."""
    env = dict(os.environ, LIVEOS_ROOT=str(ROOT))
    r = subprocess.run([sys.executable, "-I", str(COORD), *args], env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    try:
        return r.returncode, json.loads(r.stdout)
    except Exception:
        return r.returncode, (r.stdout + r.stderr).strip()


# ---------------------------------------------------------------- checks
def open_tickets():
    """(ticket, derived state) for every ticket that is not terminal, plus undelivered results."""
    out = []
    for t in co.all_tickets():
        st = co.state_of(t["id"])
        if st["state"] not in co.TERMINAL or not st["delivered"]:
            out.append((t, st))
    return out


def check_coordinator(cfg, findings, actions):
    """Dead or late Coordinator service. Whenever the service is not known to be running and
    work is open, the watchdog stands in and runs the Coordinator's own reconcile, so the stall
    guard keeps running. A service that was never started is not a fault in this checkout (it
    dies with the session that started it); a heartbeat whose process is gone, or stale, is."""
    svc, hb = co.service_state()
    late_after = int(cfg["services"].get("coordinator", {}).get("late_after_intervals", 3))
    status, why = "ok", None
    if svc == "running":
        pass
    elif hb is None:
        status, why = "not running", "no service heartbeat (.local/workflow/coordinator.json); the watchdog stands in"
    else:
        hb_age = age(hb.get("at", ""))
        interval = float(hb.get("interval", 60))
        if hb.get("mode") == "once":          # a scheduled one-shot tick leaves a heartbeat with an exited pid
            if hb_age > late_after * interval:
                status, why = "late", f"one-shot ticks stopped: last tick {human(hb_age)} ago (interval {interval:g}s)"
        elif not alive(hb.get("pid")):
            status, why = "dead", f"heartbeat pid {hb.get('pid')} is not alive; last tick {human(hb_age)} ago"
        else:
            status, why = "late", f"pid {hb.get('pid')} alive but last tick {human(hb_age)} ago (interval {interval:g}s)"
    work = open_tickets()
    did, n_actions = "nothing to do", 0
    if status != "ok" and work:
        code, out = coordinator("reconcile", "--json", "--quiet")
        if code == 0 and isinstance(out, list):
            n_actions = len(out)
            did = f"ran reconcile in its place: {n_actions} action(s)"
            for a in out:
                actions.append({"by": "reconcile", **a})
        else:
            did = f"reconcile failed (exit {code}): {str(out)[:200]}"
    elif status != "ok":
        did = "no open work, so nothing is waiting on the service"
    if status in ("dead", "late"):
        findings.append({"check": "coordinator-service", "subject": "coordinator", "status": status,
                         "why": why, "open_work": len(work), "attention": bool(work), "did": did,
                         "next": "python tools/run.py start coordinator -- python tools/coordinator.py serve"})
    return {"status": status, "why": why, "open_work": len(work), "stood_in": status != "ok" and bool(work),
            "reconcile_actions": n_actions}


def declared_relays():
    """Sessions that declared a chat notify adapter, so a relay is expected for them."""
    out = {}
    if SESSIONS.is_dir():
        for p in SESSIONS.glob("*/session.json"):
            s = read_json(p) or {}
            if s.get("notify"):
                out[p.parent.name] = s["notify"]
    return out


def unread_results(session):
    p = SESSIONS / session / "inbox.jsonl"
    if not p.is_file():
        return 0
    n = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            if not json.loads(line).get("read"):
                n += 1
        except Exception:
            continue
    return n


def check_relays(cfg, findings):
    spec = cfg["services"].get("relay", {})
    late_after = int(spec.get("late_after_intervals", 6))
    grace = float(spec.get("grace_seconds", 5))
    declared = declared_relays()
    seen = set()
    if RELAYS.is_dir():
        for p in sorted(RELAYS.glob("*.json")):
            session = p.stem
            seen.add(session)
            hb = read_json(p)
            if not hb:
                continue
            hb_age = age(hb.get("at", ""))
            interval = float(hb.get("interval", 2))
            if alive(hb.get("pid")) and hb_age <= late_after * interval + grace:
                continue
            status = "dead" if not alive(hb.get("pid")) else "late"
            unread = unread_results(session)
            findings.append({
                "check": "relay", "subject": session, "status": status,
                "why": (f"relay pid {hb.get('pid')} not alive" if status == "dead"
                        else f"relay pid {hb.get('pid')} alive but last tick {human(hb_age)} ago")
                       + f"; last tick {hb.get('at')}; {hb.get('notified', 0)} notification(s) sent in its life",
                "unread_results": unread,
                "attention": unread > 0,
                "did": "reported only; the watchdog starts no processes",
                "next": f"python tools/run.py start relay-{session} -- python tools/conversationalist.py relay --session {session}"})
    for session in sorted(set(declared) - seen):
        unread = unread_results(session)
        if unread:
            findings.append({
                "check": "relay", "subject": session, "status": "not started",
                "why": f"session declared a notify adapter but no relay heartbeat exists; {unread} unread result(s) wait",
                "unread_results": unread, "attention": True,
                "did": "reported only",
                "next": f"python tools/run.py start relay-{session} -- python tools/conversationalist.py relay --session {session}"})


def classify_run(rec, spec):
    """Same reading of a run record as tools/run.py: finished / interrupted / stalled / running."""
    if rec.get("state") in ("done", "failed", "stopped"):
        return rec["state"]
    stale = float(spec.get("stale_after_seconds", 90))
    stall = float(spec.get("stall_after_seconds", 900))
    if age(rec.get("heartbeat", "")) > stale or not alive(rec.get("pid")):
        return "interrupted"
    if age(rec.get("last_progress", "")) > stall:
        return "stalled"
    return "running"


def check_runs(cfg, findings):
    spec = cfg["services"].get("run", {})
    if not RUNS.is_dir():
        return
    leased = {}
    if co.LEASES.is_dir():
        for p in co.LEASES.glob("*.json"):
            l = read_json(p) or {}
            if l.get("run_id"):
                leased[l["run_id"]] = l["ticket"]
    for p in sorted(RUNS.glob("*.json")):
        rec = read_json(p)
        if not rec or "id" not in rec:
            continue
        status = classify_run(rec, spec)
        if status not in ("interrupted", "stalled"):
            continue
        ticket = next((t for rid, t in leased.items() if rid in rec["id"]), None)
        findings.append({
            "check": "run", "subject": rec["id"], "status": status,
            "why": (f"wrapper pid {rec.get('pid')} gone or no heartbeat for {human(age(rec.get('heartbeat', '')))}"
                    if status == "interrupted"
                    else f"alive but no CPU progress or output for {human(age(rec.get('last_progress', '')))}"),
            "ticket": ticket,
            "did": ("the Coordinator's reconcile requeues the ticket this run was working on" if ticket
                    else "reported only; read the log before re-running"),
            "log": rec.get("log"), "next": rec.get("resume")})


def attempt_started(tid, st, lease):
    """When the current attempt began: the ledger's claimed event, else the lease."""
    for e in reversed(co.events_of(tid)):
        if e.get("event") == "claimed" and e.get("attempt") == st["attempt"]:
            return e.get("at")
    return (lease or {}).get("claimed")


def check_deadlines(cfg, findings, actions, state):
    """A ticket claimed past its kind's deadline: ask for a diagnosis, once per attempt.
    Liveness is the Coordinator's business (lease, stall flag); this is about progress that
    never ends. Nothing is killed and nothing is failed."""
    escalated = state.setdefault("escalated", {})
    for t in co.all_tickets():
        tid = t["id"]
        st = co.state_of(tid)
        if st["state"] != "claimed":
            continue
        lease = read_json(co.LEASES / f"{tid}.json")
        started = attempt_started(tid, st, lease)
        if not started:
            continue
        running_for = age(started)
        limit = deadline_for(t["kind"], cfg)
        if running_for <= limit:
            continue
        key = f"watchdog:deadline:{tid}#a{st['attempt']}"
        milestone = (lease or {}).get("milestone")
        last_progress = human(age((lease or {}).get("last_progress", ""))) if lease else "unknown"
        finding = {"check": "deadline", "subject": tid, "status": "overdue", "kind": t["kind"],
                   "attempt": st["attempt"], "worker": st["worker"],
                   "running_for": human(running_for), "deadline": human(limit),
                   "last_progress_ago": last_progress, "milestone": milestone,
                   "why": f"{t['kind']} attempt {st['attempt']} has been claimed for {human(running_for)}; "
                          f"the deadline for {t['kind']} is {human(limit)} "
                          f"({(cfg.get('kinds') or {}).get(t['kind'], {}).get('reason', 'default')})",
                   "request_key": key}
        prior = escalated.get(key)
        if prior:
            finding["did"] = f"already escalated as {prior}; nothing more until the attempt changes"
            finding["diagnose"] = prior
            findings.append(finding)
            continue
        question = (f"Watchdog: {tid} ({t['kind']}, attempt {st['attempt']}, worker {st['worker']}) has been "
                    f"claimed for {human(running_for)}, past the {human(limit)} deadline for {t['kind']}. "
                    f"Last milestone: {milestone or 'none'} ({last_progress} ago). "
                    f"Is the attempt healthy and merely long, looping, or blocked? Original question: "
                    f"{(t.get('question') or '')[:300]}")
        done_when = ("Name the cause from the lifecycle records, the lease milestones and the worker's "
                     "output, and say one of: let it continue (with a new deadline), fail it with "
                     "`coordinator.py fail --force` and requeue, or re-scope the question.")
        args = ["submit", "--kind", "diagnose", "--sender", "watchdog", "--request-key", key,
                "--question", question, "--done-when", done_when]
        if t.get("scope_ref"):
            args += ["--scope-ref", t["scope_ref"]]
        if t.get("topic"):
            args += ["--topic", t["topic"]]
        session = (t.get("return_to") or {}).get("session") or (t.get("origin") or {}).get("session")
        if session:
            args += ["--session", session]
        turn = (t.get("origin") or {}).get("turn")
        if turn:
            args += ["--turn", turn]
        code, out = coordinator(*args)
        if code == 0 and isinstance(out, dict) and out.get("receipt"):
            escalated[key] = out["receipt"]
            finding["diagnose"] = out["receipt"]
            finding["did"] = (f"submitted diagnose ticket {out['receipt']}"
                              + (" (already existed: same request key)" if out.get("duplicate_of") else ""))
            actions.append({"by": "watchdog", "ticket": tid, "action": "escalated-to-diagnose",
                            "diagnose": out["receipt"], "request_key": key})
        else:
            finding["did"] = f"submit failed (exit {code}): {str(out)[:200]}"
        findings.append(finding)
    # forget escalations whose attempt is no longer the live one, so the state stays small
    live = {f"watchdog:deadline:{t['id']}#a{co.state_of(t['id'])['attempt']}" for t in co.all_tickets()
            if co.state_of(t["id"])["state"] == "claimed"}
    for key in list(escalated):
        if key not in live:
            escalated.pop(key)


# ---------------------------------------------------------------- one tick
def tick(interval, mode="once"):
    cfg = deadlines()
    prior = read_json(HEARTBEAT) or {}
    state = {"escalated": prior.get("escalated", {})}
    findings, actions, error, service = [], [], None, None
    try:
        service = check_coordinator(cfg, findings, actions)
        check_relays(cfg, findings)
        check_runs(cfg, findings)
        check_deadlines(cfg, findings, actions, state)
    except SystemExit as e:                 # a held lock or a bad record must not kill the watchdog
        error = str(e)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    attention = [f for f in findings if f.get("attention", True)]
    hb = {"pid": os.getpid(), "at": now(), "ticks": int(prior.get("ticks", 0)) + 1, "interval": interval,
          "mode": mode, "deadlines_file": str(DEADLINES.relative_to(ROOT)) if DEADLINES.is_file() else None,
          "coordinator_service": service,
          "findings": findings, "actions": actions, "attention": len(attention),
          "escalated": state["escalated"], "last_error": error}
    co.write_atomic(HEARTBEAT, hb)
    if findings or actions or error:
        try:
            with LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": hb["at"], "findings": findings, "actions": actions,
                                    "error": error}, ensure_ascii=False) + "\n")
        except OSError:
            pass
    return hb


def print_tick(hb, as_json):
    if as_json:
        print(json.dumps(hb, ensure_ascii=False, indent=1))
        return
    svc = hb.get("coordinator_service") or {}
    stood_in = f"; coordinator service {svc['status']}, watchdog ran reconcile" if svc.get("stood_in") else ""
    if not hb["findings"] and not hb["actions"] and not hb["last_error"]:
        print(f"{hb['at']} watchdog: all quiet (tick {hb['ticks']}{stood_in})")
        return
    for f in hb["findings"]:
        print(f"{hb['at']} {f['check']} {f['subject']}: {f['status'].upper()} -- {f['why']}")
        print(f"    did:  {f.get('did')}")
        if f.get("next"):
            print(f"    next: {f['next']}")
    for a in hb["actions"]:
        print(f"{hb['at']} action " + " ".join(f"{k}={v}" for k, v in a.items()))
    if hb["last_error"]:
        print(f"{hb['at']} error: {hb['last_error']}")


def serve(args):
    if not args.once:
        print(f"watchdog serving; checking every {args.interval}s", flush=True)
    while True:
        started = time.time()
        hb = tick(args.interval, "once" if args.once else "serve")
        print_tick(hb, args.json)
        sys.stdout.flush()
        if args.once:
            if hb["last_error"]:
                return 2
            return 1 if hb["attention"] else 0
        time.sleep(max(1.0, args.interval - (time.time() - started)))


def status(args):
    hb = read_json(HEARTBEAT)
    if not hb:
        print("watchdog: never run (no .local/workflow/watchdog.json)")
        return 1
    hb_age = age(hb.get("at", ""))
    running = hb.get("mode") == "serve" and alive(hb.get("pid")) and hb_age < 3 * float(hb.get("interval", 300))
    if args.json:
        print(json.dumps({**hb, "running": running, "last_tick_age_seconds": int(hb_age)}, ensure_ascii=False, indent=1))
        return 0
    print(f"watchdog: {'running' if running else 'not running'}; last tick {human(hb_age)} ago "
          f"(tick {hb.get('ticks')}, mode {hb.get('mode')}, {hb.get('attention', 0)} needing attention)")
    for f in hb.get("findings", []):
        print(f"  {f['check']} {f['subject']}: {f['status']} -- {f['why']}")
    if hb.get("last_error"):
        print(f"  error: {hb['last_error']}")
    return 1 if hb.get("attention") or hb.get("last_error") else 0


def show_deadlines(args):
    cfg = deadlines()
    if args.json:
        print(json.dumps(cfg, ensure_ascii=False, indent=1))
        return 0
    print(f"{'kind':10s} {'deadline':>9s}  reason")
    for kind in co.KINDS:
        spec = (cfg.get("kinds") or {}).get(kind) or {}
        print(f"{kind:10s} {human(deadline_for(kind, cfg)):>9s}  {spec.get('reason', 'default')}")
    print(f"source: {DEADLINES.relative_to(ROOT) if DEADLINES.is_file() else 'built-in defaults (file missing)'}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("serve")
    v.add_argument("--interval", type=int, default=300)
    v.add_argument("--once", action="store_true")
    v.add_argument("--json", action="store_true")
    v.set_defaults(func=serve)
    s = sub.add_parser("status"); s.add_argument("--json", action="store_true"); s.set_defaults(func=status)
    d = sub.add_parser("deadlines"); d.add_argument("--json", action="store_true"); d.set_defaults(func=show_deadlines)
    a = ap.parse_args()
    raise SystemExit(a.func(a))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
