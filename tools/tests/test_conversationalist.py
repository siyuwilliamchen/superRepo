"""Phase 2-3 gate for the Conversationalist (LiveOS research through conversation, section 8).

Gates carried from the design and from William's follow-up ticket (request key
liveos-conversationalist-return-relay):

- a correction survives a restart and still points at the turn it corrects;
- the same request filed twice gives one ticket, and one effective delayed result reaches the
  conversation once, with its provenance (question, time asked, revisions, claims changed);
- local and remote acknowledgment are told apart: local pending, ledger receipt, committed,
  on a remote;
- a late answer to a superseded question revision stays attributable to it and is not voiced
  as current;
- simulated and actual voice delivery are recorded as different things;
- a landed result causes exactly one chat notification without the conversation polling, and
  an unread result waits for a session that was offline;
- the writing brief names the outstanding ticket that could change the lead claim.

Every step runs the tool as a new process against a scratch root (LIVEOS_ROOT), so each
call is also a restart: nothing survives except what is on disk.

    python -m unittest tools/tests/test_conversationalist.py -v
"""
from pathlib import Path
import json, os, shutil, subprocess, sys, tempfile, unittest

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools"
SAPI_AVAILABLE = None


def sapi_available():
    global SAPI_AVAILABLE
    if SAPI_AVAILABLE is None:
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                                "Add-Type -AssemblyName System.Speech; "
                                "(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices().Count"],
                               capture_output=True, text=True, timeout=60)
            SAPI_AVAILABLE = r.returncode == 0 and r.stdout.strip().isdigit() and int(r.stdout.strip()) > 0
        except Exception:
            SAPI_AVAILABLE = False
    return SAPI_AVAILABLE


class Conversation(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="liveos-conv-"))
        (self.root / "workflow").mkdir()
        shutil.copy(REPO / "workflow" / "roster.json", self.root / "workflow" / "roster.json")
        topic = self.root / "topics" / "t1"
        topic.mkdir(parents=True)
        (topic / "index.md").write_text("# test topic\n", encoding="utf-8")
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "test")
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()
        shutil.rmtree(self.root, ignore_errors=True)

    # ---- helpers: every call is a fresh process
    def run_tool(self, tool, *args, ok=True, env_extra=None):
        env = dict(os.environ, LIVEOS_ROOT=str(self.root), **(env_extra or {}))
        r = subprocess.run([sys.executable, "-I", str(TOOLS / tool), *args], env=env,
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        if ok:
            self.assertEqual(r.returncode, 0, f"{tool} {args}\n{r.stdout}\n{r.stderr}")
        try:
            return r.returncode, json.loads(r.stdout)
        except Exception:
            return r.returncode, r.stdout + r.stderr

    def cv(self, *args, **kw):
        return self.run_tool("conversationalist.py", *args, **kw)

    def co(self, *args, **kw):
        return self.run_tool("coordinator.py", *args, **kw)

    def git(self, *args):
        r = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, encoding="utf-8")
        return r.stdout.strip()

    def open_session(self, sid="S-08", question="Who can allow or prevent the company from borrowing?"):
        return self.cv("open", "--session", sid, "--topic", "t1", "--question", question)[1]

    def say(self, sid, speaker, text):
        return self.cv("turn", "--session", sid, "--speaker", speaker, "--text", text)[1]["turn"]

    def ask(self, sid, turn, slug="amendment-check", claims="C-07", after="interpret", offline=False):
        args = ["ask", "--session", sid, "--turn", turn, "--kind", "research", "--slug", slug,
                "--question", "Did an effective amendment change the investor-consent threshold?",
                "--done-when", "Return the old and new thresholds with locators, or name the missing document.",
                "--claims", claims]
        if after:
            args += ["--after-success", after]
        if offline:
            args.append("--offline")
        return self.cv(*args)[1]

    def work_through(self, tid, summary="threshold changed from 5m to 8m", claims="C-12"):
        """A research worker and then the interpreter finish the ticket; both are other processes."""
        a = self.co("claim", "--worker", "research-agent", "--kind", "research")[1]
        self.assertEqual(a["claimed"], tid)
        self.co("complete", tid, "--attempt-id", a["attempt_id"], "--summary", summary,
                "--sources", "S:amend-2 s.4", "--claims", claims)
        child = self.co("show", tid)[1]["derived_state"]["children"]
        self.assertEqual(len(child), 1, "exactly one follow-on interpretation per research ticket")
        ia = self.co("claim", "--worker", "interpreter", "--kind", "interpret")[1]
        self.co("complete", child[0], "--attempt-id", ia["attempt_id"],
                "--summary", "the threshold in the diagram changes; approval against remedy still holds",
                "--claims", claims)
        return child[0]

    def inbox(self, sid="S-08"):
        p = self.root / "sessions" / sid / "inbox.jsonl"
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.is_file() else []

    # ---- a correction survives a restart
    def test_correction_survives_restart_and_points_back(self):
        self.open_session()
        u1 = self.say("S-08", "partner", "There are two decisions here: the board vote and the investor clause.")
        u2 = self.say("S-08", "william", "C and D feel like two explanations of the same thing.")
        o1 = self.cv("outline", "--session", "S-08", "--turn", u2, "--disposition", "inferred",
                     "--entry", "C and D are rival explanations", "--claims", "C-12,C-19")[1]["outline"]
        u3 = self.cv("correct", "--session", "S-08", "--turn", u2,
                     "--text", "No. I meant C as a condition on D.")[1]
        self.assertEqual(u3["corrects"], u2)
        o2 = self.cv("outline", "--session", "S-08", "--turn", u3["turn"], "--disposition", "explicit",
                     "--entry", "place condition C-12 at the decision it changes", "--claims", "C-12",
                     "--supersedes", o1)[1]["outline"]
        self.cv("checkpoint", "--session", "S-08")

        # restart: a new process reads only the disk
        st = self.cv("status", "--session", "S-08", "--json")[1]
        self.assertEqual(st["corrections"], [{"turn": u3["turn"], "corrects": u2,
                                              "text": "No. I meant C as a condition on D."}])
        by_id = {e["id"]: e for e in st["working_outline"]}
        self.assertEqual(by_id[o1]["status"], f"superseded by {o2}")
        self.assertEqual(by_id[o2]["status"], "current")
        self.assertEqual(by_id[o2]["disposition"], "explicit")
        ctx = self.cv("open", "--session", "S-08")[1]
        self.assertEqual([e["id"] for e in ctx["outline_current"]], [o2])
        self.assertEqual(ctx["from_checkpoint"], "cp-1")
        self.assertEqual(ctx["turns_since_checkpoint"], [])
        cp = json.loads((self.root / "sessions" / "S-08" / "checkpoints" / "0001.json").read_text(encoding="utf-8"))
        self.assertEqual([e["id"] for e in cp["confirmed_connections"]], [o2])
        # a correction without a replacing entry only questions what was inferred from that turn
        u4 = self.say("S-08", "william", "Put remedies on a separate branch.")
        o3 = self.cv("outline", "--session", "S-08", "--turn", u4, "--disposition", "inferred",
                     "--entry", "remedies as a separate branch", "--claims", "C-19")[1]["outline"]
        self.cv("correct", "--session", "S-08", "--turn", u4, "--text", "Separate page, not branch.")
        st = self.cv("status", "--session", "S-08", "--json")[1]
        self.assertTrue({e["id"]: e for e in st["working_outline"]}[o3]["status"].startswith("questioned"))
        # the durable turns are in order across segment files
        turns = self.cv("open", "--session", "S-08")[1]["turns_since_checkpoint"]
        self.assertEqual([t["id"] for t in turns], ["u-4", "u-5"])

    def test_turn_segments_keep_order(self):
        # the segment size is fixed when the session is created, so a later host cannot resplit it
        self.cv("open", "--session", "S-seg", "--topic", "t1", env_extra={"LIVEOS_TURN_SEGMENT": "3"})
        for i in range(7):
            self.cv("turn", "--session", "S-seg", "--speaker", "william", "--text", f"t{i}",
                    env_extra={"LIVEOS_TURN_SEGMENT": "3"})
        segs = sorted(p.name for p in (self.root / "sessions" / "S-seg" / "turns").glob("*.jsonl"))
        self.assertEqual(segs, ["0001.jsonl", "0002.jsonl", "0003.jsonl"])
        ctx = self.cv("open", "--session", "S-seg")[1]
        self.assertEqual([t["id"] for t in ctx["turns_since_checkpoint"]], [f"u-{i}" for i in range(1, 8)])

    # ---- one effective delayed result, with provenance
    def test_one_effective_delayed_result_with_provenance(self):
        self.open_session()
        u1 = self.say("S-08", "william", "Did a later amendment change the consent threshold?")
        first = self.ask("S-08", u1)
        self.assertEqual(first["ack"]["level"], "ledger")
        self.assertIn("Recorded as", first["say"])
        self.assertIn("not yet shared", first["say"])
        # the acknowledgment was lost; the client retries with the same key
        second = self.ask("S-08", u1)
        self.assertEqual(second["receipt"], first["receipt"])
        self.assertEqual(second["duplicate_of"], first["receipt"])
        tid = first["receipt"]
        self.assertEqual(len(list((self.root / "workflow" / "outbox" / "research").glob("*.json"))), 1)
        self.assertEqual(self.cv("status", "--session", "S-08", "--json")[1]["coverage"]["C-07"]["state"], "commissioned")

        # William keeps talking while the work runs
        u2 = self.say("S-08", "william", "Fine. Back to the board vote.")
        self.cv("outline", "--session", "S-08", "--turn", u2, "--disposition", "explicit",
                "--entry", "foreground the board vote", "--claims", "C-07,C-12")
        child = self.work_through(tid)
        self.assertEqual(len(self.inbox()), 1, "the interpretation carries the answer back, once")

        # the next natural pause: exactly one re-entry, with provenance
        out = self.cv("catchup", "--session", "S-08", "--voice", "simulated")[1]
        self.assertEqual(out["new_results"], 1)
        d = out["delivered"][0]
        self.assertEqual(d["ticket"], child)
        self.assertEqual(d["answers"], tid)
        self.assertFalse(d["superseded"])
        self.assertTrue(d["affects_current_argument"])
        self.assertIn("Did an effective amendment change the investor-consent threshold?", d["text"])
        self.assertIn("a moment ago", d["text"])
        self.assertIn("It changes C-12.", d["text"])
        self.assertIn("touches the point we are on", d["text"])
        self.assertEqual(d["spoken"]["delivery"], "simulated")
        # the re-entry is a durable partner turn whose refs are the provenance
        ctx = self.cv("open", "--session", "S-08")[1]
        reentry = [t for t in ctx["turns_since_checkpoint"] if t["kind"] == "reentry"]
        self.assertEqual(len(reentry), 1)
        turns = []
        for p in sorted((self.root / "sessions" / "S-08" / "turns").glob("*.jsonl")):
            turns += [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        refs = [t for t in turns if t["kind"] == "reentry"][0]["refs"]
        self.assertEqual(refs["answers"], tid)
        self.assertEqual(refs["origin"], {"session": "S-08", "turn": u1, "round": 1})
        self.assertEqual(refs["question_revision"], 1)
        self.assertEqual(refs["claim_ids_changed"], ["C-12"])
        self.assertTrue(refs["input_revision"].startswith("git:"))
        self.assertTrue(refs["output_revision"].startswith("git:"))
        self.assertTrue(refs["asked_at"])
        self.assertEqual(ctx["coverage"]["C-12"]["state"], "returned")
        # a second catch-up, or a restart, delivers nothing twice
        again = self.cv("catchup", "--session", "S-08")[1]
        self.assertEqual(again["new_results"], 0)
        self.assertEqual(ctx["unread_results"], 0)
        health = self.co("health", ok=False)[1]
        self.assertEqual(health["unread_results"], {}, "the Coordinator's unread view agrees")
        self.assertTrue(all(i["read"] for i in self.inbox()))

    def test_late_answer_to_a_superseded_question_is_not_voiced_as_current(self):
        self.open_session()
        u1 = self.say("S-08", "william", "Did a later amendment change the threshold?")
        tid = self.ask("S-08", u1)["receipt"]
        u2 = self.say("S-08", "william", "Actually, organise this around where the deal can be stopped.")
        rev = self.cv("revise-question", "--session", "S-08", "--turn", u2,
                      "--text", "Where can the borrowing be stopped, and by whom?")[1]
        self.assertEqual((rev["question_revision"], rev["supersedes"]), (2, 1))
        self.work_through(tid)
        out = self.cv("catchup", "--session", "S-08")[1]
        d = out["delivered"][0]
        self.assertTrue(d["superseded"])
        self.assertIn("earlier version of the question, revision 1", d["text"])
        self.assertIn("not applied", d["text"])
        st = self.cv("status", "--session", "S-08", "--json")[1]
        self.assertNotIn("C-12", st["coverage"], "a superseded result does not move coverage")
        self.assertEqual(st["governing_question"]["revision"], 2)
        self.assertEqual(len(st["tickets"]), 1)
        self.assertEqual(st["tickets"][0]["question_revision"], 1, "the ticket stays attributable to revision 1")

    # ---- local against remote acknowledgment
    def test_offline_request_is_local_then_ledger_after_flush(self):
        self.open_session()
        u1 = self.say("S-08", "william", "Check the amendment.")
        off = self.ask("S-08", u1, offline=True)
        self.assertEqual(off["ack"]["level"], "local")
        self.assertEqual(off["ack"]["shared_dispatch"], "pending")
        self.assertIn("shared ledger has not taken it yet", off["say"])
        self.assertEqual(len(list((self.root / "sessions" / "S-08" / "pending").glob("*.json"))), 1)
        self.assertFalse((self.root / "workflow" / "outbox" / "research").exists())
        ctx = self.cv("open", "--session", "S-08")[1]           # restart while still offline
        self.assertEqual(ctx["pending_local_requests"], [f"S-08/{u1}/amendment-check"])
        self.assertEqual(ctx["tickets"][0]["state"], "pending-local")
        still = self.cv("flush", "--session", "S-08", "--offline")[1]
        self.assertEqual(still["flushed"][0]["ack"], "local")
        back = self.cv("flush", "--session", "S-08")[1]
        self.assertEqual(back["flushed"][0]["ack"], "ledger")
        tid = back["flushed"][0]["receipt"]
        self.assertEqual(len(list((self.root / "workflow" / "outbox" / "research").glob("*.json"))), 1)
        self.assertEqual(self.cv("flush", "--session", "S-08")[1]["flushed"], [])
        # the original request key is the one the ledger holds
        ticket = json.loads((self.root / "workflow" / "outbox" / "research" / f"{tid}.json").read_text(encoding="utf-8"))
        self.assertEqual(ticket["request_key"], f"S-08/{u1}/amendment-check")
        self.assertEqual(ticket["origin"]["turn"], u1)

    def test_acknowledgment_levels_ledger_committed_remote(self):
        self.open_session()
        u1 = self.say("S-08", "william", "Check the amendment.")
        tid = self.ask("S-08", u1)["receipt"]
        r = self.cv("receipt", "--session", "S-08", tid)[1][0]
        self.assertEqual(r["ack"]["level"], "ledger")
        self.assertIsNone(r["ack"]["committed_in"])
        self.assertEqual(r["ack"]["remotes"], [])
        self.assertIn("not yet in a git commit", r["ack"]["note"])
        # committed locally
        self.git("add", "workflow", "sessions")
        self.git("commit", "-q", "-m", "ledger")
        r = self.cv("receipt", "--session", "S-08", tid)[1][0]
        self.assertEqual(r["ack"]["level"], "committed")
        self.assertEqual(len(r["ack"]["committed_in"]), 40)
        self.assertIn("no remote configured", r["ack"]["note"])
        # on a shared remote
        bare = Path(tempfile.mkdtemp(prefix="liveos-remote-"))
        try:
            subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
            self.git("remote", "add", "origin", str(bare))
            r = self.cv("receipt", "--session", "S-08", tid)[1][0]
            self.assertEqual(r["ack"]["level"], "committed")
            self.assertIn("no remote holds it", r["ack"]["note"])
            branch = self.git("rev-parse", "--abbrev-ref", "HEAD")
            self.git("push", "-q", "origin", branch)
            r = self.cv("receipt", "--session", "S-08", tid)[1][0]
            self.assertEqual(r["ack"]["level"], "remote")
            self.assertEqual(r["ack"]["on_remote"], [f"origin/{branch}"])
        finally:
            shutil.rmtree(bare, ignore_errors=True)

    # ---- a remote receipt is live evidence from the intended branch, or it is pending
    def git_ok(self, *args, cwd=None):
        r = subprocess.run(["git", "-C", str(cwd or self.root), *args], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, f"git {args}\n{r.stdout}\n{r.stderr}")
        return r.stdout.strip()

    def pushed_ticket(self):
        """A ticket committed on top of a base commit and pushed to a disposable bare remote.
        The receipt is 'remote' and the local remote-tracking ref says so too: from here on
        that ref is the stale witness every case below must not believe."""
        self.open_session()
        self.git_ok("add", "workflow", "topics")
        self.git_ok("commit", "-q", "-m", "base")
        base = self.git_ok("rev-parse", "HEAD")
        u1 = self.say("S-08", "william", "Check the amendment.")
        tid = self.ask("S-08", u1)["receipt"]
        self.git_ok("add", "workflow", "sessions")
        self.git_ok("commit", "-q", "-m", "ledger")
        sha = self.git_ok("rev-parse", "HEAD")
        branch = self.git_ok("rev-parse", "--abbrev-ref", "HEAD")
        bare = Path(tempfile.mkdtemp(prefix="liveos-remote-"))
        self.addCleanup(shutil.rmtree, bare, ignore_errors=True)
        self.git_ok("init", "-q", "--bare", str(bare), cwd=bare)
        self.git_ok("remote", "add", "origin", str(bare))
        self.git_ok("push", "-q", "origin", branch)
        ack = self.receipt(tid)
        self.assertEqual(ack["level"], "remote")
        self.assertEqual(ack["committed_in"], sha)
        self.assertEqual(ack["shared_remote"]["state"], "confirmed")
        self.assertEqual(ack["shared_remote"]["live_tip"], sha)
        return {"tid": tid, "bare": bare, "branch": branch, "base": base, "sha": sha}

    def receipt(self, tid, **env):
        return self.cv("receipt", "--session", "S-08", tid, env_extra=env or None)[1][0]["ack"]

    def other_clone(self, t):
        """Somebody else's checkout of the same remote."""
        other = Path(tempfile.mkdtemp(prefix="liveos-other-"))
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        self.git_ok("clone", "-q", "--branch", t["branch"], str(t["bare"]), str(other), cwd=other)
        self.git_ok("config", "user.email", "other@example.invalid", cwd=other)
        self.git_ok("config", "user.name", "other", cwd=other)
        return other

    def assert_pending(self, t, ack, reason):
        """Not 'remote', and the old evidence (the local remote-tracking ref) still claims it."""
        self.assertEqual(ack["level"], "committed", ack)
        self.assertEqual(ack["on_remote"], [])
        self.assertEqual(ack["shared_remote"]["state"], "pending")
        self.assertEqual(ack["shared_remote"]["reason"], reason, ack)
        self.assertEqual(ack["shared_remote"]["branch"], f"origin/{t['branch']}")
        self.assertEqual(ack["shared_remote"]["stale_tracking_refs"], [f"origin/{t['branch']}"])
        self.assertIn(f"origin/{t['branch']}", self.git_ok("branch", "-r", "--contains", t["sha"]),
                      "the local remote-tracking ref still lists the commit; it must not be believed")
        self.assertIn("pending", ack["note"])

    def test_remote_receipt_is_pending_when_the_live_branch_was_rewound(self):
        t = self.pushed_ticket()
        self.git_ok("update-ref", f"refs/heads/{t['branch']}", t["base"], cwd=t["bare"])
        ack = self.receipt(t["tid"])
        self.assert_pending(t, ack, "not-contained")
        self.assertEqual(ack["shared_remote"]["live_tip"], t["base"])
        # what the partner says and what the session reports follow the live answer
        st = self.cv("status", "--session", "S-08", "--json")[1]
        self.assertEqual(st["tickets"][0]["ack"]["level"], "committed")
        # pushed again: confirmed again
        self.git_ok("push", "-q", "origin", t["branch"])
        self.assertEqual(self.receipt(t["tid"])["level"], "remote")

    def test_remote_receipt_is_pending_when_the_live_branch_was_rewritten_by_someone_else(self):
        t = self.pushed_ticket()
        other = self.other_clone(t)
        self.git_ok("reset", "-q", "--hard", t["base"], cwd=other)
        self.git_ok("commit", "-q", "--allow-empty", "-m", "another history", cwd=other)
        tip = self.git_ok("rev-parse", "HEAD", cwd=other)
        self.git_ok("push", "-q", "--force", "origin", t["branch"], cwd=other)
        tracking_before = self.git_ok("rev-parse", f"refs/remotes/origin/{t['branch']}")
        ack = self.receipt(t["tid"])                 # the live tip is a commit this checkout never saw
        self.assert_pending(t, ack, "not-contained")
        self.assertEqual(ack["shared_remote"]["live_tip"], tip)
        self.assertEqual(self.git_ok("rev-parse", f"refs/remotes/origin/{t['branch']}"), tracking_before,
                         "asking the remote writes no ref in this checkout")
        self.assertFalse((self.root / ".git" / "FETCH_HEAD").exists())

    def test_remote_receipt_holds_when_someone_else_pushed_on_top(self):
        t = self.pushed_ticket()
        other = self.other_clone(t)
        self.git_ok("commit", "-q", "--allow-empty", "-m", "later work", cwd=other)
        tip = self.git_ok("rev-parse", "HEAD", cwd=other)
        self.git_ok("push", "-q", "origin", t["branch"], cwd=other)
        ack = self.receipt(t["tid"])                 # unseen tip, but it contains the ticket commit
        self.assertEqual(ack["level"], "remote", ack)
        self.assertEqual(ack["on_remote"], [f"origin/{t['branch']}"])
        self.assertEqual(ack["shared_remote"]["live_tip"], tip)
        self.assertEqual(ack["committed_in"], t["sha"])
        self.assertEqual(self.git_ok("rev-parse", f"refs/remotes/origin/{t['branch']}"), t["sha"],
                         "asking the remote writes no ref in this checkout")

    def test_remote_receipt_is_pending_when_the_remote_branch_was_deleted(self):
        t = self.pushed_ticket()
        self.git_ok("update-ref", "-d", f"refs/heads/{t['branch']}", cwd=t["bare"])
        ack = self.receipt(t["tid"])
        self.assert_pending(t, ack, "absent")
        self.assertIsNone(ack["shared_remote"]["live_tip"])
        ctx = self.cv("open", "--session", "S-08")[1]           # a restart reports the same
        self.assertEqual(ctx["tickets"][0]["ack"], "committed")

    def test_remote_receipt_is_pending_when_the_remote_cannot_be_reached(self):
        t = self.pushed_ticket()
        away = t["bare"].with_name(t["bare"].name + "-unplugged")
        self.addCleanup(shutil.rmtree, away, ignore_errors=True)
        shutil.move(str(t["bare"]), str(away))                  # the remote is there, the line is down
        ack = self.receipt(t["tid"])
        self.assert_pending(t, ack, "offline")
        self.assertIsNone(ack["shared_remote"]["live_tip"])
        # a new request filed while offline is not called shared either
        u2 = self.say("S-08", "william", "And the second amendment.")
        again = self.ask("S-08", u2, slug="second-amendment")
        self.assertEqual(again["ack"]["level"], "ledger")
        shutil.move(str(away), str(t["bare"]))                  # back online
        self.assertEqual(self.receipt(t["tid"])["level"], "remote")
        # a remote that does not answer in time is offline too
        slow = self.receipt(t["tid"], LIVEOS_REMOTE_TIMEOUT="0.001")
        self.assert_pending(t, slow, "offline")

    def test_remote_receipt_counts_only_the_intended_branch(self):
        t = self.pushed_ticket()
        self.git_ok("push", "-q", "origin", f"{t['sha']}:refs/heads/side")
        self.git_ok("update-ref", "-d", f"refs/heads/{t['branch']}", cwd=t["bare"])
        self.git_ok("update-ref", "-d", f"refs/remotes/origin/{t['branch']}")
        self.assertIn("origin/side", self.git_ok("branch", "-r", "--contains", t["sha"]))
        ack = self.receipt(t["tid"])                 # some live remote branch holds it; not the intended one
        self.assertEqual(ack["level"], "committed", ack)
        self.assertEqual(ack["shared_remote"]["reason"], "absent")
        self.assertEqual(ack["shared_remote"]["branch"], f"origin/{t['branch']}")
        # the upstream of the checked-out branch is the intended branch
        self.git_ok("fetch", "-q", "origin")
        self.git_ok("branch", "-q", "--set-upstream-to", "origin/side")
        ack = self.receipt(t["tid"])
        self.assertEqual(ack["level"], "remote", ack)
        self.assertEqual(ack["on_remote"], ["origin/side"])
        # and it can be named outright
        self.assertEqual(self.receipt(t["tid"], LIVEOS_SHARED_BRANCH=f"origin/{t['branch']}")["level"], "committed")
        bad = self.receipt(t["tid"], LIVEOS_SHARED_BRANCH="elsewhere/main")
        self.assertEqual(bad["shared_remote"]["reason"], "no-intended-branch")

    # ---- voice: simulated against actual
    def test_simulated_and_actual_voice_are_recorded_differently(self):
        self.open_session()
        u1 = self.say("S-08", "william", "Check the amendment.")
        tid = self.ask("S-08", u1)["receipt"]
        self.work_through(tid)
        wav_dir = self.root / "spoken"
        if sapi_available():
            out = self.cv("catchup", "--session", "S-08", "--voice", "sapi-wav", "--out", str(wav_dir))[1]
            sp = out["delivered"][0]["spoken"]
            self.assertEqual(sp["delivery"], "actual", sp)
            self.assertEqual(sp["adapter"], "sapi")
            self.assertTrue(sp["ok"])
            wavs = list(wav_dir.glob("*.wav"))
            self.assertEqual(len(wavs), 1)
            self.assertGreater(wavs[0].stat().st_size, 1000)
            record = json.loads((self.root / "sessions" / "S-08" / "spoken.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(record["delivery"], "actual")
            self.assertIn("nobody has heard it", record["note"])
        else:
            out = self.cv("catchup", "--session", "S-08", "--voice", "simulated")[1]
            self.assertEqual(out["delivered"][0]["spoken"]["delivery"], "simulated")
        # a second result, delivered only in simulation, is recorded as such
        u2 = self.say("S-08", "william", "And the remedy clause?")
        t2 = self.ask("S-08", u2, slug="remedy-clause", claims="C-19")["receipt"]
        self.work_through(t2, summary="remedy is damages, not invalidity", claims="C-19")
        out = self.cv("catchup", "--session", "S-08", "--voice", "simulated")[1]
        self.assertEqual(out["delivered"][0]["spoken"], {"delivery": "simulated", "adapter": "text-only",
                                                         "output": None, "ok": True, "error": None})
        records = [json.loads(l) for l in (self.root / "sessions" / "S-08" / "spoken.jsonl")
                   .read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["delivery"] for r in records],
                         ["actual" if sapi_available() else "simulated", "simulated"])

    # ---- the return relay (William's follow-up ticket)
    def test_landed_result_causes_one_chat_notification_without_polling(self):
        self.open_session()
        u1 = self.say("S-08", "william", "Check the amendment.")
        tid = self.ask("S-08", u1)["receipt"]
        chat = self.root / "chat-notifications.jsonl"       # stands in for the active chat
        self.cv("relay", "--session", "S-08", "--notify-file", str(chat), "--once")
        self.assertFalse(chat.exists(), "nothing has landed yet; nothing is said")
        # a delayed no-op completion lands while the conversation does nothing
        self.work_through(tid, summary="no change found", claims="")
        env = dict(os.environ, LIVEOS_ROOT=str(self.root))
        relay = subprocess.Popen([sys.executable, "-I", str(TOOLS / "conversationalist.py"), "relay",
                                  "--session", "S-08", "--interval", "0.5"], env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(relay)
        deadline = __import__("time").time() + 20
        while __import__("time").time() < deadline and not chat.exists():
            __import__("time").sleep(0.2)
        __import__("time").sleep(1.5)                            # long enough for a duplicate to appear if it would
        relay.kill(); relay.wait()
        notes = [json.loads(l) for l in chat.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(notes), 1, notes)
        self.assertEqual(notes[0]["answers"], tid)
        self.assertEqual(notes[0]["summary"], "the threshold in the diagram changes; approval against remedy still holds")
        self.assertIn("catchup --session S-08", notes[0]["next"])
        relays = [json.loads(l) for l in (self.root / "sessions" / "S-08" / "relays.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["delivery"] for r in relays], ["chat-notification"])
        # the notification is not speech, and the result is still unread until the conversation takes it up
        self.assertFalse((self.root / "sessions" / "S-08" / "spoken.jsonl").exists())
        st = self.cv("status", "--session", "S-08", "--json")[1]
        self.assertEqual(st["inbox"], {"total": 1, "incorporated": 0, "relayed": 1})
        # a restarted relay does not notify again
        self.assertEqual(self.cv("relay", "--session", "S-08", "--once")[1]["notified_now"], 0)
        self.assertEqual(len(chat.read_text(encoding="utf-8").splitlines()), 1)
        # the conversation incorporates it once, at its next pause
        self.assertEqual(self.cv("catchup", "--session", "S-08")[1]["new_results"], 1)

    def test_offline_session_keeps_unread_results_for_next_time(self):
        self.open_session()
        u1 = self.say("S-08", "william", "Check the amendment.")
        tid = self.ask("S-08", u1)["receipt"]
        self.cv("checkpoint", "--session", "S-08", "--note", "William left")
        self.work_through(tid)                                  # lands while nobody is listening
        # no relay ran, no catch-up ran: the next session finds it waiting
        ctx = self.cv("open", "--session", "S-08")[1]
        self.assertEqual(ctx["unread_results"], 1)
        self.assertEqual(ctx["from_checkpoint"], "cp-1")
        self.assertEqual(ctx["tickets"][0]["state"], "completed")
        health = self.co("health", ok=False)[1]
        self.assertEqual(health["unread_results"], {"S-08": 1})
        out = self.cv("catchup", "--session", "S-08")[1]
        self.assertEqual(out["new_results"], 1)
        self.assertIn("is back", out["delivered"][0]["text"])

    # ---- the frozen brief names its dependency
    def test_brief_names_the_ticket_that_could_change_the_lead(self):
        self.open_session()
        u1 = self.say("S-08", "william", "Organise it around where the deal can be stopped.")
        self.cv("outline", "--session", "S-08", "--turn", u1, "--disposition", "explicit",
                "--entry", "foreground C-07; condition C-12 at the decision it changes", "--claims", "C-07,C-12")
        self.cv("coverage", "--session", "S-08", "--point", "C-19", "--state", "deferred", "--turn", u1,
                "--note", "remedies on a separate page")
        u2 = self.say("S-08", "william", "Did the amendment change the threshold?")
        tid = self.ask("S-08", u2, claims="C-12")["receipt"]
        u3 = self.say("S-08", "william", "Good enough. Write it.")
        code, refused = self.cv("brief", "--session", "S-08", "--turn", u3, ok=False)
        self.assertEqual(code, 2)
        self.assertFalse(refused["frozen"])
        self.assertEqual(refused["dependencies"][0]["ticket"], tid)
        self.assertEqual(refused["dependencies"][0]["claims"], ["C-12"])
        self.assertFalse((self.root / "sessions" / "S-08" / "briefs").exists())
        self.assertFalse((self.root / "workflow" / "outbox" / "write").exists(), "no draft before approval")
        out = self.cv("brief", "--session", "S-08", "--turn", u3, "--accept-limitation")[1]
        self.assertTrue(out["frozen"])
        self.assertEqual(out["limitations"][0]["ticket"], tid)
        self.assertEqual(out["ack"]["level"], "ledger")
        brief = json.loads((self.root / "sessions" / "S-08" / "briefs" / "brief-1.json").read_text(encoding="utf-8"))
        self.assertEqual(brief["authorized_by_turn"], u3)
        self.assertEqual([c["claims"] for c in brief["ordered_claims"]], [["C-07", "C-12"]])
        self.assertIn("C-19", brief["deliberate_omissions"])
        write = json.loads((self.root / "workflow" / "outbox" / "write" / f"{out['write_ticket']}.json").read_text(encoding="utf-8"))
        self.assertEqual(write["claim_refs"], ["C-07", "C-12"])
        self.assertEqual(write["request_key"], f"S-08/{u3}/brief-1")
        self.assertIn("brief-1.json", write["done_when"])

    def test_requests_need_a_turn_and_a_topic_index(self):
        self.open_session()
        code, out = self.cv("ask", "--session", "S-08", "--turn", "u-9", "--kind", "research", "--slug", "x",
                            "--question", "q", "--done-when", "d", ok=False)
        self.assertNotEqual(code, 0)
        self.assertIn("no turn u-9", out)
        code, out = self.cv("open", "--session", "S-09", "--topic", "nope", ok=False)
        self.assertNotEqual(code, 0)
        self.assertIn("no topic index", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
