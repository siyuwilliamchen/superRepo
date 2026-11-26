"""The Conversationalist's durable side: the session record, William's working outline,
discussion coverage, ticket receipts with their acknowledgment level, the re-entry of
delayed results, checkpoints, the frozen writing brief, and the return relay.

Phases 2 and 3 of "LiveOS research through conversation" (William's design, 2026-11-25),
built 2026-11-25/26. What was built and where it departs from the design is in
system/methods/conversationalist.md. The talking is done by the model that runs the
role (system/agents/conversationalist.md); this tool makes every durable part of the
conversation survive a restart, a provider switch or a dead device.

  open          create or resume a session; print the starting context
  turn          append one durable turn (stable id u-N)
  correct       a correction turn that points back at the turn it corrects
  outline       one entry of William's working outline (explicit / confirmed / inferred)
  coverage      one point's discussion state
  revise-question  a new revision of the governing question; records what it supersedes
  ask           file a ticket: local pending record first, then the Coordinator's receipt
  flush         retry pending requests with the same request key
  receipt       the acknowledgment level of a ticket: local / ledger / committed / remote
  catchup       bring delivered results into the conversation, once, with provenance
  relay         push a chat notification when a result lands (no conversation polling)
  decide        one decision William made, with the turn it was made in
  checkpoint    round close: everything the next session needs to start (--next: the next action)
  workspace     what a fresh session loads first, with no session id: current topic, decisions,
                pending work and the next action, from the latest checkpoint plus what changed since
  brief         freeze the writing brief and hand it to the Writer through the Coordinator
  status        the three views, tickets and acknowledgments

All ticket traffic goes through tools/coordinator.py as a separate process: this tool never
writes the workflow ledger. It owns sessions/<session>/ only.
"""
from pathlib import Path
import argparse, datetime as dt, hashlib, json, os, re, subprocess, sys, time

sys.path.insert(0, str(Path(__file__).resolve().parent))   # python -I drops the script dir
import coordinator as co                                     # noqa: E402
import vaults                                                # noqa: E402  domain repositories as explicit inputs

ROOT, SESSIONS, TOPICS = co.ROOT, co.SESSIONS, co.TOPICS
COORD = Path(__file__).resolve().parent / "coordinator.py"
SEGMENT = int(os.environ.get("LIVEOS_TURN_SEGMENT", "200"))   # turns per durable segment
RELAY_RUNTIME = co.RUNTIME / "relays"
WORKSPACE = SESSIONS / "workspace.json"                       # private, like everything under sessions/
DISPOSITIONS = ("explicit", "confirmed", "inferred")
COVERAGE_STATES = ("unraised", "raised", "understood", "contested", "deferred", "commissioned", "returned")
VOICES = ("none", "simulated", "sapi-wav", "sapi-speaker")

now = co.now


def read_jsonl(path):
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def when_phrase(iso):
    """Plain words for how long ago something was asked."""
    try:
        secs = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(iso)).total_seconds()
    except Exception:
        return "earlier"
    if secs < 90:
        return "a moment ago"
    if secs < 3600:
        return f"{int(secs // 60)} minutes ago"
    if secs < 86400:
        h = int(secs // 3600)
        return "an hour ago" if h == 1 else f"{h} hours ago"
    return "on " + iso[:10]


def git_run(*args, timeout=20):
    """(return code, stdout, stderr). The code is None when git could not run or ran out of
    time; a credential prompt is refused instead of waited for."""
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           stdin=subprocess.DEVNULL, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return None, "", f"no answer within {timeout:g} seconds"
    except Exception as e:
        return None, "", str(e)


def git(*args):
    code, out, _ = git_run(*args)
    return out if code == 0 else None


# ---------------------------------------------------------------- the session record
class Session:
    def __init__(self, sid, create=False, topic=None, project=None, question=None, turn=None):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", sid or ""):
            raise SystemExit("conversationalist: a session id is letters, digits, . _ - only")
        self.id = sid
        self.dir = SESSIONS / sid
        self.path = self.dir / "session.json"
        if self.path.is_file():
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
            self.created = False
        elif create:
            if topic and not vaults.resolve(f"topics/{topic}/index.md"):
                raise SystemExit(f"conversationalist: no topic index topics/{topic}/index.md; "
                                 f"a session starts from one. Looked in: "
                                 + "; ".join(vaults.where_to_look(f"topics/{topic}/index.md")))
            q = ({"revision": 1, "text": question, "turn": turn, "at": now(), "supersedes": None}
                 if question else None)
            self.state = {"schema_version": 1, "id": sid, "topic": topic, "project": project,
                          "opened": now(), "adapter": "text-cli", "question": q,
                          "question_history": [q] if q else [], "turns": 0,
                          "segment_size": SEGMENT, "inbox_cursor": 0, "relay_cursor": 0,
                          "last_checkpoint": None, "notify": None}
            self.dir.mkdir(parents=True, exist_ok=True)
            self.save()
            self.created = True
        else:
            raise SystemExit(f"conversationalist: no session {sid}; open it first")

    def save(self):
        co.write_atomic(self.path, self.state)

    # -- turns, in bounded segments with stable ids
    def turns(self):
        out = []
        d = self.dir / "turns"
        if d.is_dir():
            for p in sorted(d.glob("*.jsonl")):
                out.extend(read_jsonl(p))
        return out

    def add_turn(self, speaker, text, kind="turn", corrects=None, refs=None):
        n = self.state["turns"] + 1
        seg = (n - 1) // self.state["segment_size"] + 1
        rec = {"id": f"u-{n}", "at": now(), "speaker": speaker, "kind": kind, "text": text,
               "corrects": corrects, "refs": refs or {}}
        co.append_jsonl(self.dir / "turns" / f"{seg:04d}.jsonl", rec)
        self.state["turns"] = n
        self.save()
        return rec

    def has_turn(self, tid):
        m = re.fullmatch(r"u-(\d+)", tid or "")
        return bool(m) and 0 < int(m.group(1)) <= self.state["turns"]

    # -- the working outline: append-only records, a derived current view
    def outline_records(self):
        return read_jsonl(self.dir / "outline.jsonl")

    def outline_view(self):
        recs = self.outline_records()
        entries = [r for r in recs if r.get("kind") == "entry"]
        corrections = [r for r in recs if r.get("kind") == "correction"]
        superseded = {r["supersedes"]: r["id"] for r in entries if r.get("supersedes")}
        questioned = {}
        for c in corrections:
            for e in entries:
                if e["turn"] == c["of_turn"]:
                    questioned.setdefault(e["id"], c["by_turn"])
        view = []
        for e in entries:
            if e["id"] in superseded:
                status = f"superseded by {superseded[e['id']]}"
            elif e["id"] in questioned:
                status = f"questioned: its turn {e['turn']} was corrected at {questioned[e['id']]}"
            else:
                status = "current"
            view.append({**e, "status": status})
        return view

    def current_outline(self):
        return [e for e in self.outline_view() if e["status"] == "current"]

    def current_claims(self):
        return {c for e in self.current_outline() for c in e.get("claims", [])}

    # -- coverage
    def coverage(self):
        p = self.dir / "coverage.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}

    def set_coverage(self, point, state, turn=None, note=None):
        cov = self.coverage()
        cov[point] = {"state": state, "turn": turn, "at": now(), "note": note}
        co.write_atomic(self.dir / "coverage.json", cov)
        return cov[point]

    # -- tickets this session asked for
    def ticket_records(self):
        latest = {}
        for r in read_jsonl(self.dir / "tickets.jsonl"):
            latest[r["request_key"]] = r
        return list(latest.values())

    def pending_dir(self):
        return self.dir / "pending"

    def pending(self):
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.pending_dir().glob("*.json"))]

    def inbox(self):
        return read_jsonl(self.dir / "inbox.jsonl")

    def checkpoints(self):
        d = self.dir / "checkpoints"
        return sorted(d.glob("*.json")) if d.is_dir() else []

    # -- decisions: append-only, a later one may replace an earlier one
    def decisions(self):
        return read_jsonl(self.dir / "decisions.jsonl")

    def current_decisions(self):
        recs = self.decisions()
        replaced = {r["supersedes"] for r in recs if r.get("supersedes")}
        return [r for r in recs if r["id"] not in replaced]


def pending_path(session, key):
    return session.pending_dir() / (hashlib.sha256(key.encode()).hexdigest()[:16] + ".json")


# ---------------------------------------------------------------- acknowledgment levels
def remote_timeout():
    """Seconds one question to the remote may take before the answer is 'pending'."""
    try:
        return float(os.environ.get("LIVEOS_REMOTE_TIMEOUT", "15"))
    except ValueError:
        return 15.0


def intended_branch(remotes):
    """The one remote branch a receipt may be confirmed against, as ((remote, branch), None),
    or (None, why not). LIVEOS_SHARED_BRANCH=<remote>/<branch> names it outright; otherwise it
    is the upstream of the checked-out branch, and failing that the branch of the same name on
    the push remote. Any other remote branch that happens to hold the commit does not count."""
    named = os.environ.get("LIVEOS_SHARED_BRANCH")
    if named:
        for r in sorted(remotes, key=len, reverse=True):
            if named.startswith(r + "/") and len(named) > len(r) + 1:
                return (r, named[len(r) + 1:]), None
        return None, f"LIVEOS_SHARED_BRANCH={named} does not start with a configured remote"
    head = git("symbolic-ref", "--quiet", "--short", "HEAD")
    if not head:
        return None, "HEAD is detached, so no remote branch is the intended one"
    up_remote = git("config", "--get", f"branch.{head}.remote")
    up_ref = git("config", "--get", f"branch.{head}.merge") or ""
    if up_remote in remotes and up_ref.startswith("refs/heads/"):
        return (up_remote, up_ref[len("refs/heads/"):]), None
    remote = (git("config", "--get", f"branch.{head}.pushRemote") or git("config", "--get", "remote.pushDefault")
              or ("origin" if "origin" in remotes else remotes[0] if len(remotes) == 1 else None))
    if remote not in remotes:
        return None, f"branch {head} has no upstream and the remotes ({', '.join(remotes)}) do not single one out"
    return (remote, head), None


_LIVE = {}   # (remote, branch) -> what the remote itself said, asked once per process


def live_tip(remote, branch):
    """Ask the remote, now, where the branch is. Never read from refs/remotes/: a
    remote-tracking ref is this checkout's memory of the last fetch or push, and it outlives
    a deleted branch, a rewritten one and a lost connection."""
    if (remote, branch) not in _LIVE:
        ref = f"refs/heads/{branch}"
        code, out, err = git_run("ls-remote", remote, ref, timeout=remote_timeout())
        if code != 0:
            _LIVE[(remote, branch)] = {"reachable": False, "tip": None,
                                       "error": (err.splitlines() or ["git ls-remote failed"])[-1][:200]}
        else:
            tips = [l.split()[0] for l in out.splitlines() if l.split()[1:] == [ref]]
            _LIVE[(remote, branch)] = {"reachable": True, "tip": tips[0] if tips else None, "error": None}
    return _LIVE[(remote, branch)]


def have_commit(sha):
    return git_run("cat-file", "-e", sha + "^{commit}")[0] == 0


def remote_evidence(sha, remotes):
    """Is the exact ticket commit contained in the intended branch as the remote holds it now?
    'confirmed' only on that evidence; everything else is 'pending' with the reason: no
    intended branch, remote not reachable, branch absent, branch not containing the commit,
    or a live tip whose history could not be read here."""
    out = {"state": "pending", "reason": None, "branch": None, "live_tip": None, "checked": now(),
           "stale_tracking_refs": []}
    target, why_not = intended_branch(remotes)
    if not target:
        out.update(reason="no-intended-branch", detail=why_not)
        return out
    remote, branch = target
    name = f"{remote}/{branch}"
    out["branch"] = name
    live = live_tip(remote, branch)
    tip = out["live_tip"] = live["tip"]
    if not live["reachable"]:
        out.update(reason="offline", detail=f"{remote} could not be reached ({live['error']})")
    elif not tip:
        out.update(reason="absent", detail=f"{name} does not exist on the remote")
    else:
        if tip != sha and not have_commit(tip) and not live.get("fetched"):
            # the branch moved to a commit this checkout has never seen: take its objects only.
            # No ref is written (not FETCH_HEAD, not refs/remotes/), so the check changes
            # nothing a later command would read as evidence.
            live["fetched"] = True
            git_run("fetch", "--quiet", "--no-tags", "--no-write-fetch-head", "--refmap=",
                    remote, f"refs/heads/{branch}", timeout=remote_timeout())
        if tip == sha:
            contained = 0
        elif have_commit(tip):
            contained = git_run("merge-base", "--is-ancestor", sha, tip)[0]
        else:
            contained = None
        if contained == 0:
            out.update(state="confirmed", reason=None,
                       detail=f"commit {sha[:12]} is contained in {name} at {tip[:12]}, asked of the remote just now")
        elif contained == 1:
            out.update(reason="not-contained",
                       detail=f"{name} is at {tip[:12]} on the remote, which does not contain commit {sha[:12]}")
        else:
            out.update(reason="unverified",
                       detail=f"{name} is at {tip[:12]} on the remote; its history could not be read here")
    if out["state"] != "confirmed":
        tracking = f"refs/remotes/{name}"
        if git_run("merge-base", "--is-ancestor", sha, tracking)[0] == 0:
            out["stale_tracking_refs"] = [name]
            out["detail"] += "; the local remote-tracking ref still lists the commit, which is not evidence"
    return out


def ack_of(session, key, tid):
    """local: saved in this session only. ledger: the Coordinator persisted the request and
    issued a receipt. committed: that file is in a git commit. remote: that exact commit is
    contained in the intended branch as the remote holds it at the moment of asking, which is
    the design's definition of a successful acknowledgment. A remote that cannot be reached,
    a branch that is gone or one that no longer holds the commit leaves the receipt at
    committed with shared_remote pending. Each level is checked, never assumed."""
    if pending_path(session, key).is_file() or not tid:
        return {"level": "local", "receipt": tid, "shared_dispatch": "pending",
                "note": "saved in sessions/; the Coordinator has not accepted it yet"}
    p = co.ticket_path(tid)
    if not p:
        return {"level": "none", "receipt": tid, "note": "receipt names a ticket that is not in the ledger"}
    rel = p.relative_to(ROOT).as_posix()
    inside_git = git("rev-parse", "--is-inside-work-tree") == "true"
    sha = (git("log", "-1", "--format=%H", "--", rel) or None) if inside_git else None
    remotes = (git("remote") or "").split() if inside_git else []
    shared = remote_evidence(sha, remotes) if sha and remotes else None
    confirmed = bool(shared) and shared["state"] == "confirmed"
    level = "remote" if confirmed else "committed" if sha else "ledger"
    if not inside_git:
        note = "ledger file written; this root is not a git repository, so no commit is possible"
    elif level == "ledger":
        note = "in the local ledger file, not yet in a git commit"
    elif not remotes:
        note = "committed locally; this repository has no remote configured"
    elif confirmed:
        note = "committed and on the shared remote: " + shared["detail"]
    else:
        note = "committed locally; no remote holds it on live evidence (pending): " + shared["detail"]
    return {"level": level, "receipt": tid, "persisted": rel, "committed_in": sha,
            "remotes": remotes, "on_remote": [shared["branch"]] if confirmed else [],
            "shared_remote": shared, "note": note}


def ack_words(ack, slug):
    """What the partner says out loud about a filed request, true to its level."""
    if ack["level"] == "local":
        return (f"I have saved the {slug} request here. The shared ledger has not taken it yet; "
                f"I will keep retrying with the same key, and we can go on.")
    base = f"Recorded as {ack['receipt']}: the {slug} check. I will bring it back when it lands."
    if ack["level"] == "ledger":
        return base + " It is in the local ledger, not yet shared."
    if ack["level"] == "committed":
        if (ack.get("shared_remote") or {}).get("reason") in ("offline", "unverified"):
            return base + " It is committed here; I could not confirm it on the shared remote just now."
        return base + " It is committed here, not yet on the shared remote."
    return base


# ---------------------------------------------------------------- coordinator calls
def coordinator(*args, timeout=60):
    """One process boundary: the acceptance is the Coordinator's word, not this tool's."""
    env = dict(os.environ, LIVEOS_ROOT=str(ROOT))
    r = subprocess.run([sys.executable, "-I", str(COORD), *args], env=env, capture_output=True,
                       text=True, encoding="utf-8", timeout=timeout)
    try:
        return r.returncode, json.loads(r.stdout)
    except Exception:
        return r.returncode, {"error": (r.stdout + r.stderr).strip()}


def ticket_state(tid):
    try:
        return co.state_of(tid)["state"] if co.ticket_path(tid) else "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------- commands
def cmd_open(a):
    s = Session(a.session, create=True, topic=a.topic, project=a.project,
                question=a.question, turn=a.turn)
    if not s.created and a.question and (s.state["question"] or {}).get("text") != a.question:
        raise SystemExit("conversationalist: the session already has a governing question; "
                         "use revise-question to change it")
    print(json.dumps(context_of(s), ensure_ascii=False, indent=1))
    return 0


def context_of(s):
    """Checkpoint plus everything newer: what the partner loads before the first word."""
    cps = s.checkpoints()
    cp = json.loads(cps[-1].read_text(encoding="utf-8")) if cps else None
    turns = s.turns()
    since = cp["turns"] if cp else 0
    tickets = []
    for t in s.ticket_records():
        tickets.append({"request_key": t["request_key"], "slug": t["slug"], "receipt": t.get("receipt"),
                        "kind": t["kind"], "claims": t.get("claims", []),
                        "question_revision": t.get("question_revision"),
                        "state": ticket_state(t["receipt"]) if t.get("receipt") else "pending-local",
                        "ack": ack_of(s, t["request_key"], t.get("receipt"))["level"]})
    inbox = s.inbox()
    topic = s.state.get("topic")
    return {"session": s.id, "created_now": s.created, "topic": topic,
            "topic_index": f"topics/{topic}/index.md" if topic else None,
            "interpreter_map": interpreter_map(topic, s.coverage()),
            "governing_question": s.state["question"],
            "superseded_questions": s.state["question_history"][:-1],
            "from_checkpoint": cp["id"] if cp else None,
            "turns_total": s.state["turns"],
            "turns_since_checkpoint": [{"id": t["id"], "speaker": t["speaker"], "kind": t["kind"],
                                        "text": t["text"], "corrects": t.get("corrects")}
                                       for t in turns[since:]],
            "outline_current": [{"id": e["id"], "turn": e["turn"], "disposition": e["disposition"],
                                 "entry": e["entry"], "claims": e.get("claims", [])}
                                for e in s.current_outline()],
            "coverage": s.coverage(),
            "decisions_current": [{k: d.get(k) for k in ("id", "turn", "text")} for d in s.current_decisions()],
            "next_action_at_checkpoint": (cp or {}).get("next_action"),
            "tickets": tickets,
            "pending_local_requests": [p["request_key"] for p in s.pending()],
            "unread_results": len(inbox) - s.state["inbox_cursor"],
            "relay": relay_state(s)}


def interpreter_map(topic, coverage):
    """The Interpreter's current map for this topic, read only: its revision and the important
    points not yet in coverage, each with what William would misunderstand if he missed it.
    These seed the 'unraised' view; the Conversationalist never edits the map."""
    if not topic:
        return {"status": "no topic"}
    topic_dir = vaults.resolve(f"topics/{topic}")
    claims_dir = topic_dir / "claims" if topic_dir else None
    if not claims_dir or not claims_dir.is_dir():
        return {"status": "none yet: no claims/ directory for this topic",
                "topic_owner": vaults.owner(topic_dir) if topic_dir else None}
    try:
        import claimmap
        path = claimmap.latest_map(topic_dir)
        if not path:
            return {"status": "claims/ exists but holds no map"}
        m = claimmap.load(path)
    except Exception as e:
        return {"status": f"map unreadable: {type(e).__name__}: {e}"}
    unraised = [{"id": c["id"], "title": c.get("title"), "level": c.get("level"),
                 "missed_if_skipped": c.get("missed_if_skipped")}
                for c in m.get("claims", []) if c.get("important") and c["id"] not in coverage]
    return {"status": "present", "path": str(path), "owner": vaults.owner(path), "revision": m.get("revision"),
            "claims": len(m.get("claims", [])), "open_rivals": [r.get("id") for r in m.get("rivals", [])
                                                                if r.get("status", "open") != "settled"],
            "important_unraised": unraised}


def cmd_turn(a):
    s = Session(a.session)
    if a.corrects and not s.has_turn(a.corrects):
        raise SystemExit(f"conversationalist: no turn {a.corrects} to correct")
    rec = s.add_turn(a.speaker, a.text, kind="correction" if a.corrects else "turn", corrects=a.corrects)
    if a.corrects:
        co.append_jsonl(s.dir / "outline.jsonl",
                        {"kind": "correction", "of_turn": a.corrects, "by_turn": rec["id"], "at": now()})
    print(json.dumps({"turn": rec["id"], "kind": rec["kind"], "corrects": a.corrects}, ensure_ascii=False))
    return 0


def cmd_correct(a):
    a.corrects, a.speaker = a.turn, a.speaker
    return cmd_turn(a)


def cmd_outline(a):
    s = Session(a.session)
    if not s.has_turn(a.turn):
        raise SystemExit(f"conversationalist: no turn {a.turn}; an outline entry names the turn it came from")
    recs = [r for r in s.outline_records() if r.get("kind") == "entry"]
    if a.supersedes and a.supersedes not in {r["id"] for r in recs}:
        raise SystemExit(f"conversationalist: no outline entry {a.supersedes}")
    oid = f"O-{len(recs) + 1}"
    rec = {"kind": "entry", "id": oid, "turn": a.turn, "disposition": a.disposition, "entry": a.entry,
           "claims": [c for c in (a.claims or "").split(",") if c], "scope": a.scope,
           "supersedes": a.supersedes, "at": now()}
    co.append_jsonl(s.dir / "outline.jsonl", rec)
    print(json.dumps({"outline": oid, "supersedes": a.supersedes, "disposition": a.disposition}, ensure_ascii=False))
    return 0


def cmd_coverage(a):
    s = Session(a.session)
    rec = s.set_coverage(a.point, a.state, a.turn, a.note)
    print(json.dumps({"point": a.point, **rec}, ensure_ascii=False))
    return 0


def cmd_revise_question(a):
    s = Session(a.session)
    if not s.has_turn(a.turn):
        raise SystemExit(f"conversationalist: no turn {a.turn}")
    old = s.state["question"]
    new = {"revision": (old["revision"] + 1) if old else 1, "text": a.text, "turn": a.turn, "at": now(),
           "supersedes": old["revision"] if old else None}
    s.state["question"] = new
    s.state["question_history"].append(new)
    s.save()
    print(json.dumps({"question_revision": new["revision"], "supersedes": new["supersedes"],
                      "note": "a late answer to the old revision stays attributable to it and is not "
                              "voiced as current"}, ensure_ascii=False))
    return 0


def dispatch(s, req):
    """Hand one saved request to the Coordinator. Returns the receipt or None."""
    code, out = coordinator("submit", *req["argv"])
    if code != 0 or not out.get("accepted"):
        return None, out
    pending_path(s, req["request_key"]).unlink(missing_ok=True)
    rec = {"at": now(), "request_key": req["request_key"], "slug": req["slug"], "turn": req["turn"],
           "kind": req["kind"], "question_revision": req["question_revision"], "claims": req["claims"],
           "question": req["question"], "receipt": out["receipt"], "ack": "ledger",
           "duplicate_of": out.get("duplicate_of")}
    co.append_jsonl(s.dir / "tickets.jsonl", rec)
    for c in req["claims"]:
        s.set_coverage(c, "commissioned", req["turn"], f"{req['kind']} {out['receipt']}")
    return out, rec


def cmd_ask(a):
    s = Session(a.session)
    if not s.has_turn(a.turn):
        raise SystemExit(f"conversationalist: no turn {a.turn}; a request names the turn that raised it")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", a.slug):
        raise SystemExit("conversationalist: slug is lowercase letters, digits and dashes")
    key = f"{s.id}/{a.turn}/{a.slug}"
    q = s.state["question"] or {"revision": 1}
    claims = [c for c in (a.claims or "").split(",") if c]
    argv = ["--kind", a.kind, "--question", a.question, "--done-when", a.done_when,
            "--sender", "conversationalist", "--session", s.id, "--turn", a.turn,
            "--request-key", key, "--question-revision", str(q["revision"])]
    if s.state.get("topic"):
        argv += ["--topic", s.state["topic"]]
    if s.state.get("project"):
        argv += ["--project", s.state["project"]]
    if claims:
        argv += ["--claim-refs", ",".join(claims)]
    if a.evidence_needed:
        argv += ["--evidence-needed", a.evidence_needed]
    if a.after_success:
        argv += ["--after-success", a.after_success]
    req = {"request_key": key, "slug": a.slug, "turn": a.turn, "kind": a.kind, "claims": claims,
           "question": a.question, "question_revision": q["revision"], "argv": argv, "saved": now()}
    # 1. the local acknowledgment: on disk before anything is sent
    co.write_atomic(pending_path(s, key), req)
    co.append_jsonl(s.dir / "tickets.jsonl", {"at": now(), "request_key": key, "slug": a.slug,
                                              "turn": a.turn, "kind": a.kind, "claims": claims,
                                              "question": a.question, "question_revision": q["revision"],
                                              "receipt": None, "ack": "local"})
    if a.offline:
        ack = ack_of(s, key, None)
        print(json.dumps({"request_key": key, "ack": ack, "say": ack_words(ack, a.slug),
                          "note": "disconnected: the request waits in sessions/<id>/pending; "
                                  "flush retries it with the same key"}, ensure_ascii=False, indent=1))
        return 0
    # 2. the shared acknowledgment: the Coordinator's receipt
    out, rec = dispatch(s, req)
    if out is None:
        ack = ack_of(s, key, None)
        print(json.dumps({"request_key": key, "ack": ack, "say": ack_words(ack, a.slug),
                          "coordinator_said": rec}, ensure_ascii=False, indent=1))
        return 0
    ack = ack_of(s, key, out["receipt"])
    print(json.dumps({"request_key": key, "receipt": out["receipt"], "duplicate_of": out.get("duplicate_of"),
                      "ack": ack, "say": ack_words(ack, a.slug)}, ensure_ascii=False, indent=1))
    return 0


def cmd_flush(a):
    s = Session(a.session)
    done = []
    for req in s.pending():
        if a.offline:
            done.append({"request_key": req["request_key"], "ack": "local", "note": "still disconnected"})
            continue
        out, rec = dispatch(s, req)
        if out is None:
            done.append({"request_key": req["request_key"], "ack": "local", "coordinator_said": rec})
        else:
            done.append({"request_key": req["request_key"], "receipt": out["receipt"],
                         "duplicate_of": out.get("duplicate_of"),
                         "ack": ack_of(s, req["request_key"], out["receipt"])["level"]})
    print(json.dumps({"flushed": done}, ensure_ascii=False, indent=1))
    return 0


def cmd_receipt(a):
    s = Session(a.session)
    rows = []
    for t in s.ticket_records():
        if a.ticket and t.get("receipt") != a.ticket and t["request_key"] != a.ticket:
            continue
        rows.append({"request_key": t["request_key"], "slug": t["slug"], "receipt": t.get("receipt"),
                     "state": ticket_state(t["receipt"]) if t.get("receipt") else "pending-local",
                     "ack": ack_of(s, t["request_key"], t.get("receipt"))})
    print(json.dumps(rows, ensure_ascii=False, indent=1))
    return 0


# ---------------------------------------------------------------- voice
def speak(text, mode, outdir, name):
    """Returns a delivery record. 'simulated' writes the words and synthesizes nothing;
    'sapi-wav' really synthesizes speech into a file (actual synthesis, no playback);
    'sapi-speaker' plays through the default audio device. Playback to a listener is
    never verified by this tool; the record says only what was done."""
    rec = {"at": now(), "text": text, "mode": mode}
    if mode == "none":
        return None
    if mode == "simulated":
        rec.update(delivery="simulated", adapter="text-only", output=None, ok=True)
        return rec
    env = dict(os.environ, LIVEOS_SPEAK_TEXT=text)
    if mode == "sapi-wav":
        outdir = Path(outdir or (co.RUNTIME / "spoken"))
        outdir.mkdir(parents=True, exist_ok=True)
        wav = outdir / f"{name}.wav"
        env["LIVEOS_SPEAK_WAV"] = str(wav)
    if re.search(r"[一-鿿]", text):
        env["LIVEOS_SPEAK_CULTURE"] = "zh-CN"
    script = ("Add-Type -AssemblyName System.Speech; "
              "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              "if ($env:LIVEOS_SPEAK_WAV) { $s.SetOutputToWaveFile($env:LIVEOS_SPEAK_WAV) } "
              "else { $s.SetOutputToDefaultAudioDevice() }; "
              "if ($env:LIVEOS_SPEAK_CULTURE) { $v = $s.GetInstalledVoices() | Where-Object "
              "{ $_.VoiceInfo.Culture.Name -eq $env:LIVEOS_SPEAK_CULTURE } | Select-Object -First 1; "
              "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) } }; "
              "$s.Speak($env:LIVEOS_SPEAK_TEXT); $s.Dispose(); "
              "Write-Output ('voice=' + $s.Voice.Name)")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
        ok = r.returncode == 0
        err = None if ok else (r.stderr or r.stdout).strip()[:400]
    except Exception as e:
        ok, err = False, f"{type(e).__name__}: {e}"
    if mode == "sapi-wav":
        size = wav.stat().st_size if ok and wav.is_file() else 0
        rec.update(delivery="actual" if ok and size > 1000 else "failed", adapter="sapi",
                   output=str(wav.relative_to(ROOT)) if wav.is_relative_to(ROOT) else str(wav),
                   bytes=size, ok=ok and size > 1000, error=err,
                   note="speech synthesized to a file; nobody has heard it")
    else:
        rec.update(delivery="actual" if ok else "failed", adapter="sapi", output="default audio device",
                   ok=ok, error=err, note="played through the default audio device; a listener is not verified")
    return rec


# ---------------------------------------------------------------- catch up on results
def reentry_text(item, s, affects, multiple_prefix):
    r = item.get("result") or {}
    asked = item.get("asked") or "the earlier question"
    when = when_phrase(item.get("asked_at") or item.get("at"))
    cur = (s.state["question"] or {}).get("revision", 1)
    rev = item.get("question_revision")
    if rev is not None and rev < cur:
        return (f"{multiple_prefix}An answer has come back for an earlier version of the question, "
                f"revision {rev}: \"{asked}\". You have since reframed it, so I have kept this on record "
                f"and not applied it to what we are saying now."), True
    if r.get("outcome") == "failed":
        return (f"{multiple_prefix}The check you asked for {when} could not be finished: \"{asked}\". "
                f"{r.get('summary') or ''} Next step: {r.get('next_action') or 'decide whether to retry'}."), False
    changed = r.get("claim_ids_changed") or []
    text = f"{multiple_prefix}The check you asked for {when} is back: \"{asked}\". {r.get('summary') or ''}"
    if changed:
        text += f" It changes {', '.join(changed)}."
    if affects:
        text += " That touches the point we are on."
    if r.get("uncertainty"):
        text += f" Still open: {r['uncertainty']}"
    return text.strip(), False


def cmd_catchup(a):
    s = Session(a.session)
    items = s.inbox()
    cursor = s.state["inbox_cursor"]
    new = items[cursor:]
    if not new:
        print(json.dumps({"session": s.id, "new_results": 0, "note": "nothing new; cursor unchanged"}))
        return 0
    cur_claims = s.current_claims()
    order = []
    for i, item in enumerate(new):
        changed = set((item.get("result") or {}).get("claim_ids_changed") or [])
        rev = item.get("question_revision")
        superseded = rev is not None and rev < (s.state["question"] or {}).get("revision", 1)
        order.append((superseded, not bool(changed & cur_claims), i, item, bool(changed & cur_claims)))
    order.sort(key=lambda t: (t[0], t[1], t[2]))      # current argument first, superseded last
    delivered = []
    prefix = f"{len(new)} results are back. " if len(new) > 1 else ""
    for n, (_, _, _, item, affects) in enumerate(order):
        text, superseded = reentry_text(item, s, affects, prefix if n == 0 else "")
        r = item.get("result") or {}
        refs = {"ticket": item.get("ticket"), "answers": item.get("answers"), "asked": item.get("asked"),
                "asked_at": item.get("asked_at"), "origin": item.get("origin"),
                "question_revision": item.get("question_revision"),
                "input_revision": r.get("input_revision"), "output_revision": r.get("output_revision"),
                "claim_ids_changed": r.get("claim_ids_changed"), "source_refs": r.get("source_refs"),
                "outcome": r.get("outcome"), "superseded": superseded, "delivered_at": item.get("at")}
        turn = s.add_turn("partner", text, kind="reentry", refs=refs)
        spoken = speak(text, a.voice, a.out, f"{s.id}-{turn['id']}")
        if spoken:
            spoken.update(turn=turn["id"], ticket=item.get("ticket"))
            co.append_jsonl(s.dir / "spoken.jsonl", spoken)
        if not superseded and r.get("outcome") != "failed":
            for c in r.get("claim_ids_changed") or []:
                s.set_coverage(c, "returned", turn["id"], f"result of {item.get('ticket')}")
        delivered.append({"turn": turn["id"], "ticket": item.get("ticket"), "answers": item.get("answers"),
                          "superseded": superseded, "affects_current_argument": affects, "text": text,
                          "spoken": None if not spoken else {k: spoken.get(k) for k in
                                                             ("delivery", "adapter", "output", "ok", "error")}})
    # the shared cursor: which returns this session has incorporated
    s.state["inbox_cursor"] = len(items)
    s.save()
    mark_read(s, len(items))
    print(json.dumps({"session": s.id, "new_results": len(new), "delivered": delivered},
                     ensure_ascii=False, indent=1))
    return 0


def mark_read(s, upto):
    """The inbox is appended by the Coordinator; rewriting it takes the ledger lock."""
    p = s.dir / "inbox.jsonl"
    with co.Lock():
        items = read_jsonl(p)
        for i in items[:upto]:
            i["read"] = True
        p.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")


# ---------------------------------------------------------------- the return relay
def relay_state(s):
    p = RELAY_RUNTIME / f"{s.id}.json"
    if not p.is_file():
        return {"declared": s.state.get("notify"), "running": False}
    try:
        hb = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"declared": s.state.get("notify"), "running": False}
    alive = co.process_alive(hb.get("pid")) and co.age(hb.get("at", "")) < 6 * hb.get("interval", 2) + 5
    return {"declared": s.state.get("notify"), "running": alive, "last_tick": hb.get("at"),
            "notified": hb.get("notified", 0)}


def notify(s, cfg, item):
    """One chat notification per landed result. 'file' appends a line a watcher (for example a
    Claude Code Monitor) turns into a chat message; 'command' runs the declared program with the
    notification as JSON on stdin. Neither is spoken; speech is the catch-up's business."""
    r = item.get("result") or {}
    msg = {"at": now(), "session": s.id, "ticket": item.get("ticket"), "answers": item.get("answers"),
           "asked": item.get("asked"), "outcome": r.get("outcome"), "summary": r.get("summary"),
           "claim_ids_changed": r.get("claim_ids_changed"),
           "say": f"A result is back for \"{item.get('asked')}\": {r.get('summary')}",
           "next": f"python tools/conversationalist.py catchup --session {s.id}"}
    rec = {"at": now(), "ticket": item.get("ticket"), "kind": cfg["kind"], "delivery": "chat-notification"}
    try:
        if cfg["kind"] == "file":
            co.append_jsonl(Path(cfg["path"]), msg)
            rec.update(target=cfg["path"], ok=True)
        elif cfg["kind"] == "command":
            r2 = subprocess.run(cfg["argv"], input=json.dumps(msg, ensure_ascii=False), capture_output=True,
                                text=True, encoding="utf-8", timeout=60)
            rec.update(target=cfg["argv"][0], ok=r2.returncode == 0, exit=r2.returncode,
                       output=(r2.stdout or r2.stderr).strip()[:300])
        else:
            rec.update(ok=False, error=f"unknown notify kind {cfg['kind']}")
    except Exception as e:
        rec.update(ok=False, error=f"{type(e).__name__}: {e}")
    return rec


def cmd_relay(a):
    s = Session(a.session)
    if a.notify_file or a.notify_cmd:
        cfg = ({"kind": "file", "path": str(Path(a.notify_file).resolve())} if a.notify_file
               else {"kind": "command", "argv": a.notify_cmd})
        s.state["notify"] = cfg
        s.save()
    cfg = s.state.get("notify")
    if not cfg:
        raise SystemExit("conversationalist: no notify adapter declared; give --notify-file or --notify-cmd")
    hb_path = RELAY_RUNTIME / f"{s.id}.json"
    ticks, notified = 0, 0
    if not a.once:
        print(f"relay for {s.id}: {cfg['kind']} -> {cfg.get('path') or cfg.get('argv')}; "
              f"checking the inbox every {a.interval}s", flush=True)
    while True:
        started = time.time()
        s = Session(a.session)                     # re-read: catchup may have moved cursors
        items = s.inbox()
        fired = []
        for item in items[s.state["relay_cursor"]:]:
            rec = notify(s, cfg, item)
            co.append_jsonl(s.dir / "relays.jsonl", rec)
            fired.append(rec)
            notified += 1
        if fired:
            with co.Lock():
                fresh = Session(a.session)
                fresh.state["relay_cursor"] = len(items)
                fresh.save()
            for rec in fired:
                print(now(), json.dumps(rec, ensure_ascii=False), flush=True)
        ticks += 1
        co.write_atomic(hb_path, {"pid": os.getpid(), "at": now(), "ticks": ticks, "interval": a.interval,
                                  "notified": notified, "session": s.id})
        if a.once:
            print(json.dumps({"session": s.id, "notified_now": len(fired), "relay_cursor": len(items)}))
            return 0
        time.sleep(max(0.2, a.interval - (time.time() - started)))


# ---------------------------------------------------------------- checkpoint and brief
def open_tickets(s):
    out = []
    for t in s.ticket_records():
        state = ticket_state(t["receipt"]) if t.get("receipt") else "pending-local"
        if state not in co.TERMINAL:
            out.append({**{k: t.get(k) for k in ("request_key", "slug", "receipt", "kind", "claims",
                                                  "question", "question_revision", "turn")},
                        "state": state, "ack": ack_of(s, t["request_key"], t.get("receipt"))["level"]})
    return out


def cmd_decide(a):
    s = Session(a.session)
    if not s.has_turn(a.turn):
        raise SystemExit(f"conversationalist: no turn {a.turn}; a decision names the turn it was made in")
    recs = s.decisions()
    if a.supersedes and a.supersedes not in {r["id"] for r in recs}:
        raise SystemExit(f"conversationalist: no decision {a.supersedes}")
    rec = {"id": f"D-{len(recs) + 1}", "turn": a.turn, "text": a.text, "supersedes": a.supersedes, "at": now()}
    co.append_jsonl(s.dir / "decisions.jsonl", rec)
    print(json.dumps({"decision": rec["id"], "turn": a.turn, "supersedes": a.supersedes}, ensure_ascii=False))
    return 0


def cmd_checkpoint(a):
    s = Session(a.session)
    n = len(s.checkpoints()) + 1
    cov = s.coverage()
    turns = s.turns()
    cp = {"id": f"cp-{n}", "at": now(), "session": s.id, "topic": s.state.get("topic"),
          "governing_question": s.state["question"], "question_history": s.state["question_history"],
          "map_versions": {"interpreter": None, "outline_entries": len(s.outline_records())},
          "turns": s.state["turns"], "last_turn": turns[-1]["id"] if turns else None,
          "outline_current": s.current_outline(),
          "confirmed_connections": [e for e in s.current_outline() if e["disposition"] in ("explicit", "confirmed")],
          "decisions": s.current_decisions(), "decisions_recorded": len(s.decisions()),
          "unresolved_disagreements": {k: v for k, v in cov.items() if v["state"] == "contested"},
          "deferred_points": {k: v for k, v in cov.items() if v["state"] == "deferred"},
          "open_tickets": open_tickets(s),
          "last_delivered_event": {"inbox_cursor": s.state["inbox_cursor"], "relay_cursor": s.state["relay_cursor"]},
          "next_action": {"text": a.next, "turn": turns[-1]["id"] if turns else None} if a.next else None,
          "note": a.note}
    path = s.dir / "checkpoints" / f"{n:04d}.json"
    co.write_atomic(path, cp)
    s.state["last_checkpoint"] = cp["id"]
    s.save()
    # the workspace pointer: what a fresh session, knowing no session id, loads first
    co.write_atomic(WORKSPACE, {"schema_version": 1, "written": now(), "session": s.id, "checkpoint": cp["id"],
                                "checkpoint_path": path.relative_to(ROOT).as_posix(),
                                "checkpoint_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                                "current_topic": topic_of(s.state.get("topic"), cp["governing_question"]),
                                "decisions": cp["decisions"], "next_action": cp["next_action"],
                                "pending_work_at_checkpoint": {
                                    "open_tickets": [t["receipt"] or t["request_key"] for t in cp["open_tickets"]],
                                    "deferred": sorted(cp["deferred_points"]),
                                    "contested": sorted(cp["unresolved_disagreements"])}})
    print(json.dumps({"checkpoint": cp["id"], "turns": cp["turns"], "open_tickets": len(cp["open_tickets"]),
                      "decisions": len(cp["decisions"]), "next_action": a.next,
                      "path": f"sessions/{s.id}/checkpoints/{n:04d}.json",
                      "workspace": "sessions/workspace.json"}, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- the workspace
def topic_of(topic, question):
    return {"topic": topic, "topic_index": f"topics/{topic}/index.md" if topic else None,
            "governing_question": ({"revision": question.get("revision"), "text": question.get("text")}
                                   if question else None)}


def latest_checkpoint_anywhere():
    """The newest checkpoint of any session, by the time written inside it."""
    best = None
    if SESSIONS.is_dir():
        for p in sorted(SESSIONS.glob("*/checkpoints/*.json")):
            try:
                cp = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if best is None or (cp.get("at") or "") >= (best[1].get("at") or ""):
                best = (p, cp)                              # on a tie the later file wins
    return best


def workspace_view(session_id=None):
    """Current topic, decisions, pending work and next action for a session that has just started.

    The checkpoint is the base. Everything that can have moved since is read again now: ticket
    states from the ledger, results in the inbox, requests still saved locally, decisions and
    turns recorded after the checkpoint. A missing or stale pointer file is rebuilt from the
    newest checkpoint on disk and the view says so."""
    named = bool(session_id)
    if not named:
        # the newest checkpoint on disk decides; the pointer file is only believed if it agrees
        found = latest_checkpoint_anywhere()
        if not found:
            return {"workspace": "empty", "note": "no checkpoint in any session; nothing to resume. "
                                                  "Open a session and close its first round with checkpoint."}
        session_id = found[1].get("session") or found[0].parents[1].name
    s = Session(session_id)
    cps = s.checkpoints()
    if not cps:
        return {"workspace": "empty", "session": s.id,
                "note": f"session {s.id} has no checkpoint yet; open it for its full context: "
                        f"python tools/conversationalist.py open --session {s.id}"}
    cp_path = cps[-1]
    cp = json.loads(cp_path.read_text(encoding="utf-8"))
    if named:
        source, pointer_state = "session named on the command line", None
    else:
        pointer = None
        if WORKSPACE.is_file():
            try:
                pointer = json.loads(WORKSPACE.read_text(encoding="utf-8"))
            except Exception:
                pointer = None
        if not isinstance(pointer, dict):
            pointer_state = "sessions/workspace.json is missing or unreadable"
        elif pointer.get("session") != s.id:
            pointer_state = (f"pointer names session {pointer.get('session')}, which is not where the newest "
                             f"checkpoint is; the checkpoint on disk was used")
        elif (pointer.get("checkpoint") != cp["id"] or
              pointer.get("checkpoint_sha256") != hashlib.sha256(cp_path.read_bytes()).hexdigest()):
            pointer_state = "pointer is older than or differs from the latest checkpoint; the checkpoint on disk was used"
        else:
            pointer_state = "matches the latest checkpoint"
        source = ("sessions/workspace.json" if pointer_state == "matches the latest checkpoint"
                  else "rebuilt from the newest checkpoint on disk")
    since = s.state["turns"] - cp["turns"]
    at_cp = {d["id"] for d in cp.get("decisions", [])}
    decisions = [{"id": d["id"], "turn": d["turn"], "text": d["text"], "at": d.get("at"),
                  "since_checkpoint": d["id"] not in at_cp} for d in s.current_decisions()]
    tickets = open_tickets(s)
    unread = len(s.inbox()) - s.state["inbox_cursor"]
    local = [p["request_key"] for p in s.pending()]
    cov = s.coverage()
    pending = {"open_tickets": [{k: t.get(k) for k in ("receipt", "request_key", "kind", "slug", "state",
                                                       "ack", "question", "claims")} for t in tickets],
               "unread_results": unread, "requests_saved_locally": local,
               "contested": {k: v.get("note") for k, v in cov.items() if v["state"] == "contested"},
               "deferred": {k: v.get("note") for k, v in cov.items() if v["state"] == "deferred"}}
    explicit = cp.get("next_action")
    recorded = ({"text": explicit["text"], "basis": f"recorded at {cp['id']}, turn {explicit.get('turn')}"}
                if explicit else None)
    tool = "python tools/conversationalist.py"
    if unread:
        nxt = {"text": f"Bring back the {unread} result(s) that landed while the session was closed, "
                       f"before anything else.", "basis": "derived: unread results in the inbox",
               "command": f"{tool} catchup --session {s.id}", "then": recorded}
    elif local:
        nxt = {"text": f"Hand the {len(local)} locally saved request(s) to the Coordinator.",
               "basis": "derived: requests saved locally and not yet accepted",
               "command": f"{tool} flush --session {s.id}", "then": recorded}
    elif recorded:
        nxt = dict(recorded, command=f"{tool} open --session {s.id}", then=None)
    elif tickets:
        nxt = {"text": f"No next action was recorded. {len(tickets)} ticket(s) are still out; go on with the "
                       f"conversation and bring each result back when it lands.",
               "basis": "derived: open tickets, no recorded next action",
               "command": f"{tool} open --session {s.id}", "then": None}
    else:
        nxt = {"text": "No next action was recorded and nothing is pending.",
               "basis": "derived: nothing recorded", "command": f"{tool} open --session {s.id}", "then": None}
    return {"workspace": "loaded", "source": source or "session named on the command line",
            "pointer": pointer_state, "session": s.id, "checkpoint": cp["id"], "checkpoint_at": cp["at"],
            "checkpoint_note": cp.get("note"), "turns_since_checkpoint": since,
            "last_turn_at_checkpoint": cp.get("last_turn"),
            "current_topic": topic_of(s.state.get("topic"), s.state["question"]),
            "decisions": decisions, "pending_work": pending, "next_action": nxt}


def cmd_workspace(a):
    v = workspace_view(a.session)
    if a.json:
        print(json.dumps(v, ensure_ascii=False, indent=1))
        return 0
    if v["workspace"] != "loaded":
        print(f"workspace: {v['workspace']}. {v['note']}")
        return 0
    t = v["current_topic"]
    q = t["governing_question"] or {}
    print(f"workspace  session {v['session']}, checkpoint {v['checkpoint']} of {v['checkpoint_at']}"
          f"  ({v['turns_since_checkpoint']} turn(s) since)  [{v['source']}]")
    if v["checkpoint_note"]:
        print(f"  note at checkpoint: {v['checkpoint_note']}")
    print(f"current topic   {t['topic']}" + (f"  ({t['topic_index']})" if t["topic_index"] else ""))
    print(f"                question rev {q.get('revision')}: {q.get('text')}")
    print("decisions" + ("" if v["decisions"] else "       none recorded"))
    for d in v["decisions"]:
        print(f"  {d['id']} ({d['turn']}) {d['text']}" + ("  [after the checkpoint]" if d["since_checkpoint"] else ""))
    p = v["pending_work"]
    nothing = not (p["open_tickets"] or p["unread_results"] or p["requests_saved_locally"]
                   or p["contested"] or p["deferred"])
    print("pending work" + ("    none" if nothing else ""))
    for k in p["open_tickets"]:
        print(f"  {k['receipt'] or '(local)':8s} {k['kind']:9s} {k['state']:13s} ack={k['ack']:9s} {k['slug']}: {k['question']}")
    if p["unread_results"]:
        print(f"  {p['unread_results']} result(s) landed and not yet brought into the conversation")
    if p["requests_saved_locally"]:
        print(f"  {len(p['requests_saved_locally'])} request(s) saved locally, not yet accepted by the Coordinator")
    for name in ("contested", "deferred"):
        for point, note in p[name].items():
            print(f"  {name}: {point}" + (f" ({note})" if note else ""))
    n = v["next_action"]
    print(f"next action     {n['text']}  [{n['basis']}]")
    print(f"                {n['command']}")
    if n.get("then"):
        print(f"  then          {n['then']['text']}  [{n['then']['basis']}]")
    return 0


def cmd_brief(a):
    s = Session(a.session)
    if not s.has_turn(a.turn):
        raise SystemExit(f"conversationalist: no turn {a.turn}; the brief names the turn that authorised it")
    entries = s.current_outline()
    lead = {c for e in entries for c in e.get("claims", [])}
    outstanding = open_tickets(s)
    blocking = [t for t in outstanding if set(t.get("claims") or []) & lead]
    if blocking and not a.accept_limitation:
        print(json.dumps({"frozen": False, "reason": "an outstanding ticket could change the argument",
                          "dependencies": [{"ticket": t["receipt"] or t["request_key"], "claims": t["claims"],
                                            "question": t["question"], "state": t["state"]} for t in blocking],
                          "choices": ["wait for it", "narrow the report (drop or background those claims)",
                                      "publish with the limitation: --accept-limitation"]},
                         ensure_ascii=False, indent=1))
        return 2
    cov = s.coverage()
    delivered = [t for t in s.turns() if t["kind"] == "reentry" and not (t["refs"] or {}).get("superseded")]
    n = len(list((s.dir / "briefs").glob("*.json"))) if (s.dir / "briefs").is_dir() else 0
    n += 1
    brief = {"id": f"brief-{n}", "at": now(), "session": s.id, "topic": s.state.get("topic"),
             "authorized_by_turn": a.turn, "governing_question": s.state["question"],
             "audience": a.audience, "reading_budget": a.budget,
             "ordered_claims": [{"outline": e["id"], "turn": e["turn"], "disposition": e["disposition"],
                                 "entry": e["entry"], "claims": e.get("claims", [])} for e in entries],
             "required_qualifications": [e for e in entries if e.get("scope")],
             "evidence_and_interpretation_revisions": [
                 {"ticket": t["refs"].get("ticket"), "input_revision": t["refs"].get("input_revision"),
                  "output_revision": t["refs"].get("output_revision"),
                  "claims": t["refs"].get("claim_ids_changed")} for t in delivered],
             "deliberate_omissions": {k: v for k, v in cov.items() if v["state"] == "deferred"},
             "outstanding_disagreements": {k: v for k, v in cov.items() if v["state"] == "contested"},
             "limitations": [{"ticket": t["receipt"] or t["request_key"], "claims": t["claims"],
                              "question": t["question"]} for t in blocking],
             "figure_ideas": a.figures, "conversation_revision": {"turns": s.state["turns"]}}
    co.write_atomic(s.dir / "briefs" / f"{brief['id']}.json", brief)
    q = (s.state["question"] or {}).get("text") or s.state.get("topic") or s.id
    argv = ["--kind", "write", "--question", f"Write the report for: {q}",
            "--done-when", f"Publication sources that build to HTML and PDF, following sessions/{s.id}/briefs/{brief['id']}.json "
                           f"exactly: its order, its qualifications, its omissions and its limitations.",
            "--sender", "conversationalist", "--session", s.id, "--turn", a.turn,
            "--request-key", f"{s.id}/{a.turn}/{brief['id']}",
            "--question-revision", str((s.state["question"] or {}).get("revision", 1))]
    if s.state.get("topic"):
        argv += ["--topic", s.state["topic"]]
    if lead:
        argv += ["--claim-refs", ",".join(sorted(lead))]
    req = {"request_key": f"{s.id}/{a.turn}/{brief['id']}", "slug": brief["id"], "turn": a.turn, "kind": "write",
           "claims": sorted(lead), "question": argv[3],
           "question_revision": (s.state["question"] or {}).get("revision", 1), "argv": argv, "saved": now()}
    co.write_atomic(pending_path(s, req["request_key"]), req)
    out, rec = dispatch(s, req)
    print(json.dumps({"frozen": True, "brief": f"sessions/{s.id}/briefs/{brief['id']}.json",
                      "limitations": brief["limitations"],
                      "write_ticket": out["receipt"] if out else None,
                      "ack": ack_of(s, req["request_key"], out["receipt"] if out else None)},
                     ensure_ascii=False, indent=1))
    return 0


def cmd_status(a):
    s = Session(a.session)
    view = {"session": s.id, "governing_question": s.state["question"],
            "interpreter_map": context_of(s)["interpreter_map"],
            "working_outline": s.outline_view(), "coverage": s.coverage(),
            "turns": s.state["turns"],
            "corrections": [{"turn": t["id"], "corrects": t["corrects"], "text": t["text"]}
                            for t in s.turns() if t["kind"] == "correction"],
            "tickets": [{**t, "state": ticket_state(t["receipt"]) if t.get("receipt") else "pending-local",
                         "ack": ack_of(s, t["request_key"], t.get("receipt"))} for t in s.ticket_records()],
            "pending_local": [p["request_key"] for p in s.pending()],
            "inbox": {"total": len(s.inbox()), "incorporated": s.state["inbox_cursor"],
                      "relayed": s.state["relay_cursor"]},
            "spoken": read_jsonl(s.dir / "spoken.jsonl"), "relay": relay_state(s),
            "checkpoints": [p.name for p in s.checkpoints()]}
    if a.json:
        print(json.dumps(view, ensure_ascii=False, indent=1))
        return 0
    q = view["governing_question"] or {}
    print(f"session {s.id}  question rev {q.get('revision')}: {q.get('text')}")
    print(f"turns {view['turns']}  corrections {len(view['corrections'])}  "
          f"inbox {view['inbox']['incorporated']}/{view['inbox']['total']} incorporated  "
          f"relay {'running' if view['relay']['running'] else 'not running'}")
    print("outline:")
    for e in view["working_outline"]:
        print(f"  {e['id']} {e['turn']} {e['disposition']:9s} {e['status']:40s} {e['entry']}")
    print("tickets:")
    for t in view["tickets"]:
        print(f"  {t.get('receipt') or '(pending)':8s} {t['kind']:9s} {t['state']:12s} ack={t['ack']['level']:9s} {t['slug']}")
    return 0


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def S(p):
        p.add_argument("--session", required=True)
        return p

    o = S(sub.add_parser("open"))
    o.add_argument("--topic"); o.add_argument("--project"); o.add_argument("--question"); o.add_argument("--turn")
    o.set_defaults(func=cmd_open)

    t = S(sub.add_parser("turn"))
    t.add_argument("--speaker", required=True, choices=["william", "partner"])
    t.add_argument("--text", required=True); t.add_argument("--corrects", default=None)
    t.set_defaults(func=cmd_turn)

    c = S(sub.add_parser("correct"))
    c.add_argument("--turn", required=True, help="the turn being corrected")
    c.add_argument("--text", required=True); c.add_argument("--speaker", default="william", choices=["william", "partner"])
    c.set_defaults(func=cmd_correct)

    ol = S(sub.add_parser("outline"))
    ol.add_argument("--turn", required=True); ol.add_argument("--disposition", required=True, choices=DISPOSITIONS)
    ol.add_argument("--entry", required=True); ol.add_argument("--claims"); ol.add_argument("--scope")
    ol.add_argument("--supersedes")
    ol.set_defaults(func=cmd_outline)

    cv = S(sub.add_parser("coverage"))
    cv.add_argument("--point", required=True); cv.add_argument("--state", required=True, choices=COVERAGE_STATES)
    cv.add_argument("--turn"); cv.add_argument("--note")
    cv.set_defaults(func=cmd_coverage)

    rq = S(sub.add_parser("revise-question"))
    rq.add_argument("--turn", required=True); rq.add_argument("--text", required=True)
    rq.set_defaults(func=cmd_revise_question)

    k = S(sub.add_parser("ask"))
    k.add_argument("--turn", required=True); k.add_argument("--kind", required=True, choices=co.KINDS)
    k.add_argument("--slug", required=True); k.add_argument("--question", required=True)
    k.add_argument("--done-when", dest="done_when", required=True)
    k.add_argument("--claims"); k.add_argument("--evidence-needed", dest="evidence_needed")
    k.add_argument("--after-success", dest="after_success", choices=[*co.KINDS, None], default=None)
    k.add_argument("--offline", action="store_true", help="simulate a lost connection: save locally only")
    k.set_defaults(func=cmd_ask)

    fl = S(sub.add_parser("flush")); fl.add_argument("--offline", action="store_true"); fl.set_defaults(func=cmd_flush)

    rc = S(sub.add_parser("receipt")); rc.add_argument("ticket", nargs="?"); rc.set_defaults(func=cmd_receipt)

    cu = S(sub.add_parser("catchup"))
    cu.add_argument("--voice", choices=VOICES, default="simulated")
    cu.add_argument("--out", default=None, help="directory for synthesized audio (sapi-wav)")
    cu.set_defaults(func=cmd_catchup)

    rl = S(sub.add_parser("relay"))
    rl.add_argument("--notify-file", dest="notify_file"); rl.add_argument("--notify-cmd", dest="notify_cmd", nargs="+")
    rl.add_argument("--interval", type=float, default=2.0); rl.add_argument("--once", action="store_true")
    rl.set_defaults(func=cmd_relay)

    dc = S(sub.add_parser("decide"))
    dc.add_argument("--turn", required=True, help="the turn the decision was made in")
    dc.add_argument("--text", required=True); dc.add_argument("--supersedes", help="the decision this one replaces")
    dc.set_defaults(func=cmd_decide)

    cp = S(sub.add_parser("checkpoint")); cp.add_argument("--note")
    cp.add_argument("--next", help="the next action, in one sentence, for whoever resumes")
    cp.set_defaults(func=cmd_checkpoint)

    ws = sub.add_parser("workspace")
    ws.add_argument("--session", default=None, help="default: the session of the latest checkpoint")
    ws.add_argument("--json", action="store_true")
    ws.set_defaults(func=cmd_workspace)

    b = S(sub.add_parser("brief"))
    b.add_argument("--turn", required=True); b.add_argument("--audience", default="William")
    b.add_argument("--budget", default="one sitting"); b.add_argument("--figures", default=None)
    b.add_argument("--accept-limitation", dest="accept_limitation", action="store_true")
    b.set_defaults(func=cmd_brief)

    st = S(sub.add_parser("status")); st.add_argument("--json", action="store_true"); st.set_defaults(func=cmd_status)

    a = ap.parse_args()
    raise SystemExit(a.func(a))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
