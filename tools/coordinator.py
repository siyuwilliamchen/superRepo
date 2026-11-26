"""The Coordinator: sole owner of the workflow ledger.

Phase 1 of "LiveOS research through conversation" (William's design, 2026-11-25).
What was built, the worker contract and the departures from the design are in
system/methods/coordinator.md. Roles never address each other; every handoff goes
through here.

  submit      record an immutable request, return a receipt (idempotent on request_key)
  claim       lease a queued ticket to one worker attempt
  progress    a worker reports a milestone (runtime state, not the ledger)
  complete    land a result; only the currently authorised attempt may publish
  fail        land a failure, with or without a retry
  reconcile   the stall guard: expired leases, stalled workers, missed children,
              undelivered results. Safe to run every minute; does nothing when idle.
  status      derived view of the queue
  show        one ticket with its full lifecycle
  deliver     (used by reconcile) place a result in a session inbox

Serialisation: one exclusive lock plus atomic file replacement. Ledger transitions are
plain files meant to be committed to git; heartbeats stay in .local/ runtime state, as
the spec requires. This departs from the spec's "atomic Git ref updates": the CAS
primitive here is the lock file and an expected-revision check on each ticket's event
sequence, not a git ref. Durability to git is a separate, batched step.
"""
from pathlib import Path
import argparse, datetime as dt, hashlib, json, os, subprocess, sys, time, uuid

ROOT = Path(os.environ.get("LIVEOS_ROOT") or Path(__file__).resolve().parents[1]).resolve()
WORKFLOW = ROOT / "workflow"
OUTBOX = WORKFLOW / "outbox"
EVENTS = WORKFLOW / "events"
ROSTER = WORKFLOW / "roster.json"
SESSIONS = ROOT / "sessions"
TOPICS = ROOT / "topics"
RUNTIME = ROOT / ".local" / "workflow"
LEASES = RUNTIME / "leases"
LOCK = RUNTIME / "ledger.lock"

KINDS = ("research", "interpret", "write", "diagnose", "build")   # build: a development assignment (added 2026-11-26)
TERMINAL = ("completed", "failed", "canceled", "superseded")
LEASE_SECONDS = 1800          # a claim must be renewed by progress within this
STALL_SECONDS = 900           # claimed, alive, but no progress for this long
MAX_ATTEMPTS = 3              # then route to diagnose instead of requeueing

# Domain repositories are explicit external inputs (config/vaults.json). A scope reference is
# looked up under this root first, then under each registered vault. python -I drops the script
# directory from sys.path, hence the explicit insert.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from vaults import resolve as resolve_ref, where_to_look   # noqa: E402


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def age(iso):
    try:
        return (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(iso)).total_seconds()
    except Exception:
        return 1e9


def git_revision():
    try:
        r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=20)
        return "git:" + r.stdout.strip() if r.returncode == 0 else "git:unknown"
    except Exception:
        return "git:unknown"


def write_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex[:8])
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


class Lock:
    """One writer at a time. Stale locks older than 120 s are broken, with a note."""

    def __enter__(self):
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + 60
        while True:
            try:
                fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f'{{"pid": {os.getpid()}, "at": "{now()}"}}'.encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    held = json.loads(LOCK.read_text(encoding="utf-8"))
                    if age(held.get("at", "")) > 120:
                        LOCK.unlink(missing_ok=True)
                        continue
                except Exception:
                    LOCK.unlink(missing_ok=True)
                    continue
                if time.time() > deadline:
                    raise SystemExit("coordinator: ledger lock held too long; another writer is stuck")
                time.sleep(0.2)

    def __exit__(self, *exc):
        LOCK.unlink(missing_ok=True)


# ---------------------------------------------------------------- ledger reads
def ticket_path(tid):
    for kind in KINDS:
        p = OUTBOX / kind / f"{tid}.json"
        if p.is_file():
            return p
    return None


def load_ticket(tid):
    p = ticket_path(tid)
    if not p:
        raise SystemExit(f"coordinator: no ticket {tid}")
    return json.loads(p.read_text(encoding="utf-8"))


def events_of(tid):
    d = EVENTS / tid
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return sorted(out, key=lambda e: e.get("sequence", 0))


def state_of(tid):
    """Derived, never stored: the ledger is the event sequence."""
    st = {"state": "queued", "attempt": 0, "worker": None, "result": None,
          "delivered": False, "children": [], "attempts_started": 0}
    for e in events_of(tid):
        k = e.get("event")
        if k == "claimed":
            st.update(state="claimed", attempt=e["attempt"], worker=e["worker"])
            st["attempts_started"] += 1
        elif k in ("completed", "failed", "canceled", "superseded"):
            st.update(state=e["event"], result=e.get("result"))
        elif k == "requeued":
            st.update(state="queued", worker=None)
        elif k == "delivered":
            st["delivered"] = True
        elif k == "child_created":
            st["children"].append(e["child"])
    return st


def all_tickets():
    out = []
    for kind in KINDS:
        d = OUTBOX / kind
        if d.is_dir():
            for p in sorted(d.glob("*.json")):
                try:
                    out.append(json.loads(p.read_text(encoding="utf-8")))
                except Exception:
                    continue
    return out


def find_by_request_key(key):
    for t in all_tickets():
        if t.get("request_key") == key:
            return t
    return None


def next_sequence(tid):
    return len(list((EVENTS / tid).glob("*.json"))) if (EVENTS / tid).is_dir() else 0


def record(tid, event, **fields):
    """Append one lifecycle record. Sequence numbers are the expected-revision check."""
    seq = next_sequence(tid)
    payload = {"ticket": tid, "sequence": seq, "event": event, "at": now(), **fields}
    path = EVENTS / tid / f"{seq:04d}-{event}.json"
    if path.exists():
        raise SystemExit(f"coordinator: event {seq} already exists for {tid}; re-read and retry")
    write_atomic(path, payload)
    return payload


def new_id(kind):
    existing = [t["id"] for t in all_tickets()]
    n = len(existing) + 1
    while f"T-{n:04d}" in existing:
        n += 1
    return f"T-{n:04d}"


# ---------------------------------------------------------------- roster
def roster():
    if not ROSTER.is_file():
        return {"roles": {}}
    return json.loads(ROSTER.read_text(encoding="utf-8"))


def eligible(kind):
    r = roster()["roles"]
    return [name for name, spec in r.items() if kind in spec.get("capabilities", [])]


# ---------------------------------------------------------------- submit
def submit(args):
    scope_ref = args.scope_ref or (f"topics/{args.topic}/index.md" if args.topic else None)
    if scope_ref and not resolve_ref(scope_ref):
        raise SystemExit(f"coordinator: scope_ref does not exist: {scope_ref}\n"
                         f"  looked in: " + "; ".join(where_to_look(scope_ref)) + "\n"
                         f"  create the topic index first; a worker must be able to start there")
    if args.kind not in KINDS:
        raise SystemExit(f"coordinator: kind must be one of {', '.join(KINDS)}")
    if not eligible(args.kind):
        raise SystemExit(f"coordinator: no role in workflow/roster.json advertises '{args.kind}'")
    with Lock():
        if args.request_key:
            prior = find_by_request_key(args.request_key)
            if prior:
                # Idempotent: the same request key never creates a second ticket.
                print(json.dumps({"receipt": prior["id"], "duplicate_of": prior["id"],
                                  "request_key": args.request_key, "accepted": True,
                                  "note": "existing ticket with this request_key"}, indent=1))
                return 0
        tid = new_id(args.kind)
        ticket = {"schema_version": 1, "id": tid, "kind": args.kind, "from": args.sender,
                  "project": args.project, "topic": args.topic,
                  "origin": {"session": args.session, "turn": args.turn, "round": args.round},
                  "request_key": args.request_key or f"{args.session}/{args.turn}/{tid}",
                  "question_revision": args.question_revision,
                  "input_revision": git_revision(),
                  "claim_refs": args.claim_refs.split(",") if args.claim_refs else [],
                  "question": args.question, "scope_ref": scope_ref,
                  "evidence_needed": args.evidence_needed, "done_when": args.done_when,
                  "after_success": args.after_success,
                  "return_to": {"session": args.session, "topic": args.topic},
                  "submitted": now()}
        write_atomic(OUTBOX / args.kind / f"{tid}.json", ticket)
        record(tid, "created", by=args.sender, request_key=ticket["request_key"],
               eligible=eligible(args.kind))
        print(json.dumps({"receipt": tid, "accepted": True, "kind": args.kind,
                          "request_key": ticket["request_key"],
                          "persisted": f"workflow/outbox/{args.kind}/{tid}.json"}, indent=1))
    return 0


# ---------------------------------------------------------------- claim / progress
def claim(args):
    with Lock():
        candidates = []
        for t in all_tickets():
            st = state_of(t["id"])
            if st["state"] == "queued" and (args.kind in (None, t["kind"])):
                candidates.append((t, st))
        if not candidates:
            print(json.dumps({"claimed": None, "note": "nothing queued"}))
            return 1
        ticket, st = candidates[0]
        tid = ticket["id"]
        if args.worker not in eligible(ticket["kind"]) and not args.force:
            raise SystemExit(f"coordinator: worker '{args.worker}' does not advertise "
                             f"'{ticket['kind']}' in the roster (use --force to override)")
        attempt = st["attempts_started"] + 1
        attempt_id = f"{tid}#a{attempt}-{uuid.uuid4().hex[:6]}"
        record(tid, "claimed", worker=args.worker, attempt=attempt, attempt_id=attempt_id,
               lease_seconds=LEASE_SECONDS, run_id=args.run_id)
        write_atomic(LEASES / f"{tid}.json",
                     {"ticket": tid, "attempt": attempt, "attempt_id": attempt_id,
                      "worker": args.worker, "pid": args.pid,
                      "run_id": args.run_id, "claimed": now(), "last_progress": now(),
                      "milestone": "claimed"})
        print(json.dumps({"claimed": tid, "attempt_id": attempt_id, "kind": ticket["kind"],
                          "question": ticket["question"], "scope_ref": ticket["scope_ref"],
                          "done_when": ticket["done_when"]}, indent=1))
    return 0


def progress(args):
    """Runtime state only: heartbeats never enter the ledger."""
    p = LEASES / f"{args.ticket}.json"
    if not p.is_file():
        raise SystemExit(f"coordinator: no active lease for {args.ticket}")
    lease = json.loads(p.read_text(encoding="utf-8"))
    if args.attempt_id and lease["attempt_id"] != args.attempt_id:
        raise SystemExit(f"coordinator: stale attempt; {args.attempt_id} no longer holds the lease")
    lease.update(last_progress=now(), milestone=args.milestone or lease.get("milestone"))
    write_atomic(p, lease)
    print(json.dumps({"ticket": args.ticket, "milestone": lease["milestone"], "noted": lease["last_progress"]}))
    return 0


# ---------------------------------------------------------------- complete / fail
def child_request_key(tid, kind):
    """Deterministic, so a crash between parent completion and child creation
    can only ever produce one child."""
    return "child:" + hashlib.sha256(f"{tid}->{kind}".encode()).hexdigest()[:16]


def _authorised(tid, attempt_id, force):
    lease = LEASES / f"{tid}.json"
    if force:
        return
    if not lease.is_file():
        raise SystemExit(f"coordinator: {tid} has no lease; claim it before completing")
    held = json.loads(lease.read_text(encoding="utf-8"))["attempt_id"]
    if attempt_id != held:
        raise SystemExit(f"coordinator: attempt {attempt_id} is not the authorised attempt "
                         f"({held}); its result is discarded")


def complete(args):
    with Lock():
        ticket = load_ticket(args.ticket)
        st = state_of(args.ticket)
        if st["state"] in TERMINAL:
            print(json.dumps({"ticket": args.ticket, "already": st["state"],
                              "note": "terminal; this result is ignored"}, indent=1))
            return 0
        _authorised(args.ticket, args.attempt_id, args.force)
        result = {"question_revision": ticket.get("question_revision"),
                  "input_revision": ticket.get("input_revision"),
                  "output_revision": git_revision(),
                  "outcome": args.outcome,
                  "claim_ids_changed": args.claims.split(",") if args.claims else [],
                  "source_refs": args.sources.split(",") if args.sources else [],
                  "uncertainty": args.uncertainty, "next_action": args.next_action,
                  "summary": args.summary, "artifact": args.artifact,
                  "return_to": ticket.get("return_to")}
        record(args.ticket, "completed", worker=st["worker"], attempt=st["attempt"],
               attempt_id=args.attempt_id, result=result)
        (LEASES / f"{args.ticket}.json").unlink(missing_ok=True)
        print(json.dumps({"ticket": args.ticket, "state": "completed",
                          "next": ticket.get("after_success") or "deliver"}, indent=1))
    # The immediate event: route the follow-on or the delivery now, not at the next tick.
    # If this process dies right here, the minute check does the same thing, exactly once.
    reconcile_once()
    return 0


def fail(args):
    with Lock():
        st = state_of(args.ticket)
        if st["state"] in TERMINAL:
            print(json.dumps({"ticket": args.ticket, "already": st["state"]}))
            return 0
        _authorised(args.ticket, args.attempt_id, args.force)
        if args.retry and st["attempts_started"] < MAX_ATTEMPTS:
            record(args.ticket, "requeued", reason=args.reason, after_attempt=st["attempt"])
            (LEASES / f"{args.ticket}.json").unlink(missing_ok=True)
            print(json.dumps({"ticket": args.ticket, "state": "queued", "reason": args.reason}))
        else:
            record(args.ticket, "failed", worker=st["worker"], attempt=st["attempt"],
                   result={"outcome": "failed", "summary": args.reason,
                           "blocker": args.blocker, "next_action": args.next_action})
            (LEASES / f"{args.ticket}.json").unlink(missing_ok=True)
            print(json.dumps({"ticket": args.ticket, "state": "failed", "reason": args.reason}))
    return 0


# ---------------------------------------------------------------- stall guard
def run_record(run_id):
    if not run_id:
        return None
    for p in (ROOT / ".local" / "runs").glob(f"*{run_id}*.json"):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def process_alive(pid):
    if not pid:
        return False
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259
    except Exception:
        try:
            os.kill(int(pid), 0)
            return True
        except OSError:
            return False


def spawn_child(parent, kind, question, done_when, input_revision):
    """Create the follow-on ticket for a parent at most once (deterministic request key).
    Returns the new id, or None if the child already exists."""
    key = child_request_key(parent["id"], kind)
    if find_by_request_key(key):
        return None
    cid = new_id(kind)
    child = dict(parent)
    child.update({"schema_version": 1, "id": cid, "kind": kind, "from": "coordinator",
                  "request_key": key, "parent": parent["id"], "after_success": None,
                  "question": question, "done_when": done_when,
                  "input_revision": input_revision or parent.get("input_revision"),
                  "submitted": now()})
    write_atomic(OUTBOX / kind / f"{cid}.json", child)
    record(cid, "created", by="coordinator", request_key=key, parent=parent["id"])
    record(parent["id"], "child_created", child=cid, kind=kind)
    return cid


def root_question(ticket):
    """Walk up to the request William (or a role) originally made."""
    seen = set()
    while ticket.get("parent") and ticket["parent"] not in seen:
        seen.add(ticket["id"])
        ticket = load_ticket(ticket["parent"])
    return ticket


def deliver(ticket, result):
    """Place a result in the session inbox, named by the question that was first asked."""
    session = (ticket.get("return_to") or {}).get("session")
    if not session:
        return None
    origin = root_question(ticket)
    append_jsonl(SESSIONS / session / "inbox.jsonl",
                 {"at": now(), "ticket": ticket["id"], "kind": ticket["kind"],
                  "answers": origin["id"], "asked": origin.get("question"),
                  "asked_at": origin.get("submitted"), "origin": origin.get("origin"),
                  "question_revision": ticket.get("question_revision"),
                  "result": result, "read": False})
    record(ticket["id"], "delivered", session=session)
    return session


def reconcile(args):
    """The stall guard. Idempotent; prints only what it changed."""
    actions = reconcile_once()
    if args.json:
        print(json.dumps(actions, indent=1))
    elif actions:
        for a in actions:
            print(" ".join(f"{k}={v}" for k, v in a.items()))
    elif not args.quiet:
        print("nothing to reconcile")
    return 0


HEARTBEAT = RUNTIME / "coordinator.json"


def serve(args):
    """The minute check as a service. An idle tick makes no model call, writes nothing to
    the ledger and creates no commit; it only refreshes its own heartbeat in runtime state.
    Run it under the run ledger so its own death is reported at the next session start:

        python tools/run.py start coordinator -- python tools/coordinator.py serve
    """
    ticks = 0
    print(f"coordinator serving; reconcile every {args.interval}s", flush=True)
    while True:
        started = time.time()
        try:
            actions = reconcile_once()
            error = None
        except SystemExit as e:           # a held lock or a bad record must not kill the service
            actions, error = [], str(e)
        except Exception as e:
            actions, error = [], f"{type(e).__name__}: {e}"
        ticks += 1
        write_atomic(HEARTBEAT, {"pid": os.getpid(), "at": now(), "ticks": ticks,
                                 "interval": args.interval, "last_error": error})
        for a in actions:
            print(now(), " ".join(f"{k}={v}" for k, v in a.items()), flush=True)
        if error:
            print(now(), "error:", error, flush=True)
        if args.once:
            return 0
        time.sleep(max(1.0, args.interval - (time.time() - started)))


def service_state():
    """Who watches the watcher: status and the session-start hook both read this."""
    if not HEARTBEAT.is_file():
        return "not running", None
    try:
        hb = json.loads(HEARTBEAT.read_text(encoding="utf-8"))
    except Exception:
        return "not running", None
    late = age(hb.get("at", "")) > 3 * hb.get("interval", 60)
    if late or not process_alive(hb.get("pid")):
        return "stopped", hb
    return "running", hb


def reconcile_once():
    actions = []
    with Lock():
        for ticket in all_tickets():
            tid = ticket["id"]
            st = state_of(tid)

            # 1. claimed tickets whose worker is gone or wedged
            if st["state"] == "claimed":
                lease_path = LEASES / f"{tid}.json"
                if not lease_path.is_file():
                    record(tid, "requeued", reason="lease file missing", after_attempt=st["attempt"])
                    actions.append({"ticket": tid, "action": "requeued", "why": "lease missing"})
                    continue
                lease = json.loads(lease_path.read_text(encoding="utf-8"))
                run = run_record(lease.get("run_id"))
                if run:
                    # a run that ended without completing its ticket is a dead worker
                    dead = run.get("state") != "running" or not process_alive(run.get("pid"))
                elif lease.get("pid"):
                    dead = not process_alive(lease["pid"])
                else:
                    dead = False  # an agent worker has no process to check; the lease clock decides
                expired = age(lease["last_progress"]) > LEASE_SECONDS
                idle = age(run["last_progress"]) if run and run.get("last_progress") else age(lease["last_progress"])
                if dead or expired:
                    why = "worker process gone" if dead else f"lease expired ({int(age(lease['last_progress']))}s)"
                    if st["attempts_started"] >= MAX_ATTEMPTS:
                        record(tid, "failed", worker=lease["worker"], attempt=st["attempt"],
                               result={"outcome": "failed", "summary": why,
                                       "blocker": f"{st['attempts_started']} attempts exhausted",
                                       "next_action": "diagnose"})
                        lease_path.unlink(missing_ok=True)
                        did = spawn_child(
                            ticket, "diagnose",
                            f"Why did {tid} fail {st['attempts_started']} attempts ({why})?",
                            "Name the cause with evidence from the lifecycle records, and give "
                            "either a repair or the one decision that is needed.", None)
                        actions.append({"ticket": tid, "action": "failed-to-diagnose", "why": why,
                                        "diagnose": did})
                    else:
                        record(tid, "requeued", reason=why, after_attempt=st["attempt"])
                        lease_path.unlink(missing_ok=True)
                        actions.append({"ticket": tid, "action": "requeued", "why": why})
                elif idle > STALL_SECONDS:
                    if not any(e.get("event") == "stalled" and e.get("attempt") == st["attempt"]
                               for e in events_of(tid)):
                        record(tid, "stalled", worker=lease["worker"], attempt=st["attempt"],
                               idle_seconds=int(idle), milestone=lease.get("milestone"),
                               note="alive but no progress; diagnose before killing")
                        actions.append({"ticket": tid, "action": "flagged-stalled",
                                        "why": f"no progress for {int(idle)}s",
                                        "milestone": lease.get("milestone")})
                continue

            # 2. completed work whose follow-on was never created (exactly-once child)
            if st["state"] == "completed":
                nxt = ticket.get("after_success")
                if nxt and nxt in KINDS:
                    cid = spawn_child(
                        ticket, nxt, f"[{nxt}] {ticket['question']}",
                        f"Act on the result of {tid} and return the compact difference "
                        f"from the previous conclusion.",
                        (st["result"] or {}).get("output_revision"))
                    if cid:
                        actions.append({"ticket": tid, "action": "child-created", "child": cid, "kind": nxt})
                    # The follow-on carries the answer back; the parent is not delivered on its own.
                    continue

                # 3. results that were never delivered to the session
                if not st["delivered"]:
                    session = deliver(ticket, st["result"])
                    if session:
                        actions.append({"ticket": tid, "action": "delivered", "session": session})
            if st["state"] == "failed" and not st["delivered"]:
                session = deliver(ticket, st["result"])
                if session:
                    actions.append({"ticket": tid, "action": "delivered-failure", "session": session})

    return actions


# ---------------------------------------------------------------- views
def status(args):
    rows = []
    for ticket in all_tickets():
        st = state_of(ticket["id"])
        lease = LEASES / f"{ticket['id']}.json"
        idle = ""
        if st["state"] == "claimed" and lease.is_file():
            l = json.loads(lease.read_text(encoding="utf-8"))
            run = run_record(l.get("run_id"))
            secs = age(run["last_progress"]) if run and run.get("last_progress") else age(l["last_progress"])
            idle = f"{int(secs)}s"
            stalled = secs > STALL_SECONDS  # computed live, so it clears when progress resumes
        else:
            stalled = False
        rows.append({"id": ticket["id"], "kind": ticket["kind"],
                     "state": "stalled" if (stalled and st["state"] == "claimed") else st["state"],
                     "idle": idle, "delivered": st["delivered"],
                     "question": (ticket.get("question") or "")[:58],
                     "topic": ticket.get("topic"), "children": st["children"]})
    if args.json:
        print(json.dumps(rows, indent=1))
        return 0
    svc, hb = service_state()
    print(f"coordinator service: {svc}" + (f" (last tick {int(age(hb['at']))}s ago)" if hb else "")
          + ("" if svc == "running" else
             "  -> start: python tools/run.py start coordinator -- python tools/coordinator.py serve"))
    if not rows:
        print("no tickets")
        return 0
    print(f"{'id':8s} {'kind':10s} {'state':10s} {'idle':>6s} {'sent':5s} question")
    for r in rows:
        print(f"{r['id']:8s} {r['kind']:10s} {r['state']:10s} {r['idle']:>6s} "
              f"{'yes' if r['delivered'] else '-':5s} {r['question']}")
    bad = [r for r in rows if r["state"] in ("stalled", "failed")]
    if bad:
        print()
        for r in bad:
            print(f"{r['state'].upper()} {r['id']}: python tools/coordinator.py show {r['id']}")
    return 1 if bad else 0


def health(args):
    """One machine-readable answer to 'does anything need attention?', for the session-start
    hook and for any adapter. Runs a reconcile first, so every session start is also a tick."""
    try:
        actions = reconcile_once()
    except SystemExit as e:
        actions = [{"action": "reconcile-skipped", "why": str(e)}]
    svc, hb = service_state()
    open_n, problems = 0, []
    for ticket in all_tickets():
        st = state_of(ticket["id"])
        if st["state"] in ("queued", "claimed"):
            open_n += 1
        lease = LEASES / f"{ticket['id']}.json"
        if st["state"] == "claimed" and lease.is_file():
            l = json.loads(lease.read_text(encoding="utf-8"))
            if age(l["last_progress"]) > STALL_SECONDS:
                problems.append({"id": ticket["id"], "state": "stalled", "kind": ticket["kind"],
                                 "idle_seconds": int(age(l["last_progress"])),
                                 "milestone": l.get("milestone"), "question": ticket.get("question")})
        if st["state"] == "failed":
            problems.append({"id": ticket["id"], "state": "failed", "kind": ticket["kind"],
                             "question": ticket.get("question"),
                             "why": (st["result"] or {}).get("summary")})
    unread = {}
    if SESSIONS.is_dir():
        for box in SESSIONS.glob("*/inbox.jsonl"):
            n = sum(1 for l in box.read_text(encoding="utf-8").splitlines()
                    if l.strip() and not json.loads(l).get("read"))
            if n:
                unread[box.parent.name] = n
    report = {"service": svc, "open_tickets": open_n, "problems": problems,
              "unread_results": unread, "just_reconciled": actions}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    attention = problems or unread or (open_n and svc != "running")
    return 1 if attention else 0


def show(args):
    ticket = load_ticket(args.ticket)
    st = state_of(args.ticket)
    print(json.dumps({"ticket": ticket, "derived_state": st,
                      "events": events_of(args.ticket)}, ensure_ascii=False, indent=1))
    return 0


def inbox(args):
    p = SESSIONS / args.session / "inbox.jsonl"
    if not p.is_file():
        print("no inbox")
        return 0
    items = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.json:
        print(json.dumps(items, indent=1))
        return 0
    for i in items:
        r = i.get("result") or {}
        print(f"{i['at']}  {i['ticket']} answers {i.get('answers')}: {i.get('asked')}")
        print(f"    {r.get('outcome')}: {r.get('summary')}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("submit")
    s.add_argument("--kind", required=True, choices=KINDS)
    s.add_argument("--question", required=True)
    s.add_argument("--done-when", required=True, dest="done_when")
    s.add_argument("--sender", default="conversationalist")
    s.add_argument("--project", default=None)
    s.add_argument("--topic", default=None)
    s.add_argument("--scope-ref", dest="scope_ref", default=None)
    s.add_argument("--session", default=None)
    s.add_argument("--turn", default=None)
    s.add_argument("--round", type=int, default=1)
    s.add_argument("--request-key", dest="request_key", default=None)
    s.add_argument("--question-revision", dest="question_revision", type=int, default=1)
    s.add_argument("--claim-refs", dest="claim_refs", default=None)
    s.add_argument("--evidence-needed", dest="evidence_needed", default=None)
    s.add_argument("--after-success", dest="after_success", default=None, choices=[*KINDS, None])
    s.set_defaults(func=submit)

    c = sub.add_parser("claim")
    c.add_argument("--worker", required=True)
    c.add_argument("--kind", default=None, choices=[*KINDS, None])
    c.add_argument("--run-id", dest="run_id", default=None)
    c.add_argument("--pid", type=int, default=None)
    c.add_argument("--force", action="store_true")
    c.set_defaults(func=claim)

    p = sub.add_parser("progress")
    p.add_argument("ticket")
    p.add_argument("--attempt-id", dest="attempt_id", default=None)
    p.add_argument("--milestone", default=None)
    p.set_defaults(func=progress)

    k = sub.add_parser("complete")
    k.add_argument("ticket")
    k.add_argument("--attempt-id", dest="attempt_id", default=None)
    k.add_argument("--outcome", default="ok")
    k.add_argument("--summary", required=True)
    k.add_argument("--claims", default=None)
    k.add_argument("--sources", default=None)
    k.add_argument("--uncertainty", default=None)
    k.add_argument("--next-action", dest="next_action", default=None)
    k.add_argument("--artifact", default=None)
    k.add_argument("--force", action="store_true")
    k.set_defaults(func=complete)

    f = sub.add_parser("fail")
    f.add_argument("ticket")
    f.add_argument("--attempt-id", dest="attempt_id", default=None)
    f.add_argument("--reason", required=True)
    f.add_argument("--blocker", default=None)
    f.add_argument("--next-action", dest="next_action", default=None)
    f.add_argument("--retry", action="store_true")
    f.add_argument("--force", action="store_true")
    f.set_defaults(func=fail)

    r = sub.add_parser("reconcile")
    r.add_argument("--json", action="store_true")
    r.add_argument("--quiet", action="store_true")
    r.set_defaults(func=reconcile)

    v = sub.add_parser("serve")
    v.add_argument("--interval", type=int, default=60)
    v.add_argument("--once", action="store_true")
    v.set_defaults(func=serve)

    t = sub.add_parser("status"); t.add_argument("--json", action="store_true"); t.set_defaults(func=status)
    h = sub.add_parser("health"); h.set_defaults(func=health)
    w = sub.add_parser("show"); w.add_argument("ticket"); w.set_defaults(func=show)
    i = sub.add_parser("inbox"); i.add_argument("session"); i.add_argument("--json", action="store_true")
    i.set_defaults(func=inbox)

    a = ap.parse_args()
    raise SystemExit(a.func(a))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
