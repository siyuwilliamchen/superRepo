"""Gate for the Conversationalist's persistent workspace (tools/conversationalist.py workspace).

A session that has just started knows nothing: no session id, no memory of the last one. The
workspace is what it loads first. What must hold:

- a fresh process, given no session id, gets the current topic, the decisions, the pending work
  and the next action from the latest checkpoint;
- what moved after the checkpoint is read again at load time: a ticket that finished is no
  longer pending, a result that landed is pending and comes before the recorded next action,
  a decision made later is shown and marked as later;
- a decision names the turn it was made in, and a replaced decision is not shown as current;
- a lost, corrupt or stale pointer file is rebuilt from the checkpoints on disk;
- an empty workspace says so instead of inventing a state;
- the workspace lives under sessions/, which git ignores.

Every step runs the tool as a new process against a scratch root (LIVEOS_ROOT), so each call
is a restart: nothing survives except what is on disk. All content is invented for the test.

    python -m unittest tools/tests/test_workspace.py -v
"""
from pathlib import Path
import json, os, shutil, subprocess, sys, tempfile, unittest

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools"
QUESTION = "Which of three test widgets should ship first?"
NEXT = "Ask William whether widget B waits for the supplier answer."


class Workspace(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="liveos-workspace-"))
        (self.root / "workflow").mkdir()
        shutil.copy(REPO / "workflow" / "roster.json", self.root / "workflow" / "roster.json")
        for t in ("t1", "t2"):
            (self.root / "topics" / t).mkdir(parents=True)
            (self.root / "topics" / t / "index.md").write_text(f"# test topic {t}\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_tool(self, tool, *args, ok=True):
        r = subprocess.run([sys.executable, "-I", str(TOOLS / tool), *args],
                           env=dict(os.environ, LIVEOS_ROOT=str(self.root), LIVEOS_REMOTE_TIMEOUT="5"),
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        if ok:
            self.assertEqual(r.returncode, 0, f"{tool} {args}\n{r.stdout}\n{r.stderr}")
        try:
            return r.returncode, json.loads(r.stdout)
        except Exception:
            return r.returncode, r.stdout + r.stderr

    def cv(self, *args, **kw):
        return self.run_tool("conversationalist.py", *args, **kw)[1]

    def co(self, *args, **kw):
        return self.run_tool("coordinator.py", *args, **kw)[1]

    def say(self, sid, speaker, text):
        return self.cv("turn", "--session", sid, "--speaker", speaker, "--text", text)["turn"]

    def fresh(self, *args):
        """What a session that has just started sees: no session id, only the disk."""
        return self.cv("workspace", "--json", *args)

    def round_one(self, sid="S-1", topic="t1"):
        """One round of an invented conversation, closed with a checkpoint."""
        self.cv("open", "--session", sid, "--topic", topic, "--question", QUESTION)
        u1 = self.say(sid, "william", "Ship A first. B depends on a supplier.")
        d1 = self.cv("decide", "--session", sid, "--turn", u1, "--text", "Ship widget A first.")["decision"]
        u2 = self.say(sid, "william", "Actually A and C together. And leave pricing for later.")
        d2 = self.cv("decide", "--session", sid, "--turn", u2, "--supersedes", d1,
                     "--text", "Ship widgets A and C together.")["decision"]
        d3 = self.cv("decide", "--session", sid, "--turn", u2, "--text", "Pricing is out of scope this round.")["decision"]
        self.cv("coverage", "--session", sid, "--point", "C-pricing", "--state", "deferred", "--turn", u2,
                "--note", "next round")
        ticket = self.cv("ask", "--session", sid, "--turn", u1, "--kind", "research", "--slug", "supplier-date",
                         "--question", "When can the supplier deliver the part for widget B?",
                         "--done-when", "A date with its source, or the name of who must be asked.",
                         "--claims", "C-b")["receipt"]
        cp = self.cv("checkpoint", "--session", sid, "--note", "round one closed", "--next", NEXT)
        return {"sid": sid, "u1": u1, "u2": u2, "d1": d1, "d2": d2, "d3": d3, "ticket": ticket, "cp": cp}

    # ---- the reload
    def test_fresh_session_reloads_topic_decisions_pending_and_next_action(self):
        r = self.round_one()
        self.assertEqual(r["cp"]["workspace"], "sessions/workspace.json")
        self.assertTrue((self.root / "sessions" / "workspace.json").is_file())

        ws = self.fresh()                                   # no --session: a session that knows nothing
        self.assertEqual(ws["workspace"], "loaded")
        self.assertEqual(ws["source"], "sessions/workspace.json")
        self.assertEqual(ws["pointer"], "matches the latest checkpoint")
        self.assertEqual((ws["session"], ws["checkpoint"], ws["checkpoint_note"]), ("S-1", "cp-1", "round one closed"))
        self.assertEqual(ws["turns_since_checkpoint"], 0)
        # current topic
        self.assertEqual(ws["current_topic"], {"topic": "t1", "topic_index": "topics/t1/index.md",
                                               "governing_question": {"revision": 1, "text": QUESTION}})
        # decisions: the replaced one is gone, each names its turn
        self.assertEqual([(d["id"], d["turn"], d["text"], d["since_checkpoint"]) for d in ws["decisions"]],
                         [(r["d2"], r["u2"], "Ship widgets A and C together.", False),
                          (r["d3"], r["u2"], "Pricing is out of scope this round.", False)])
        # pending work
        p = ws["pending_work"]
        self.assertEqual([(t["receipt"], t["kind"], t["state"], t["ack"], t["slug"]) for t in p["open_tickets"]],
                         [(r["ticket"], "research", "queued", "ledger", "supplier-date")])
        self.assertEqual((p["unread_results"], p["requests_saved_locally"]), (0, []))
        self.assertEqual(p["deferred"], {"C-pricing": "next round"})
        self.assertEqual(p["contested"], {})
        # next action: the one recorded at the checkpoint, with where it came from
        n = ws["next_action"]
        self.assertEqual(n["text"], NEXT)
        self.assertEqual(n["basis"], f"recorded at cp-1, turn {r['u2']}")
        self.assertIsNone(n["then"])
        self.assertIn("open --session S-1", n["command"])

        # the same four things, in words, for a person or a model reading the terminal
        text = self.run_tool("conversationalist.py", "workspace")[1]
        for needle in ("current topic   t1", QUESTION, "decisions", "Ship widgets A and C together.",
                       "pending work", "supplier-date", "deferred: C-pricing", "next action", NEXT):
            self.assertIn(needle, text)
        self.assertNotIn("Ship widget A first.", text, "a replaced decision is not current")
        # the checkpoint itself carries the decisions and the next action, so `open` has them too
        ctx = self.cv("open", "--session", "S-1")
        self.assertEqual(ctx["next_action_at_checkpoint"]["text"], NEXT)
        self.assertEqual([d["id"] for d in ctx["decisions_current"]], [r["d2"], r["d3"]])

    def test_reload_reads_again_what_moved_after_the_checkpoint(self):
        r = self.round_one()
        # after the session closed: a worker finishes the ticket, the result lands in the inbox
        a = self.co("claim", "--worker", "research-agent", "--kind", "research")
        self.co("complete", r["ticket"], "--attempt-id", a["attempt_id"], "--summary", "the part ships in week 9",
                "--claims", "C-b")
        ws = self.fresh()
        self.assertEqual(ws["pending_work"]["open_tickets"], [], "a finished ticket is not pending")
        self.assertEqual(ws["pending_work"]["unread_results"], 1)
        n = ws["next_action"]
        self.assertEqual(n["basis"], "derived: unread results in the inbox")
        self.assertIn("catchup --session S-1", n["command"])
        self.assertEqual(n["then"]["text"], NEXT, "the recorded action follows the catch-up; it is not lost")
        text = self.run_tool("conversationalist.py", "workspace")[1]
        self.assertIn("1 result(s) landed and not yet brought into the conversation", text)
        self.assertIn("then", text)

        # the fresh session does what the workspace says, then goes on
        self.cv("catchup", "--session", "S-1", "--voice", "none")
        u = self.say("S-1", "william", "Then B ships in week 10.")
        d4 = self.cv("decide", "--session", "S-1", "--turn", u, "--text", "Widget B ships in week 10.")["decision"]
        self.cv("ask", "--session", "S-1", "--turn", u, "--kind", "research", "--slug", "week-10-capacity",
                "--question", "Is there capacity in week 10?", "--done-when", "Yes or no with the source.",
                "--offline")
        ws = self.fresh()
        self.assertEqual(ws["pending_work"]["unread_results"], 0)
        self.assertEqual(ws["turns_since_checkpoint"], 2, "the re-entry turn and William's")
        self.assertEqual([(d["id"], d["since_checkpoint"]) for d in ws["decisions"]],
                         [(r["d2"], False), (r["d3"], False), (d4, True)])
        self.assertEqual(ws["pending_work"]["requests_saved_locally"], ["S-1/" + u + "/week-10-capacity"])
        self.assertEqual([t["state"] for t in ws["pending_work"]["open_tickets"]], ["pending-local"])
        self.assertEqual(ws["next_action"]["basis"], "derived: requests saved locally and not yet accepted")
        self.assertIn("flush --session S-1", ws["next_action"]["command"])
        self.cv("flush", "--session", "S-1")
        ws = self.fresh()
        self.assertEqual(ws["next_action"]["text"], NEXT, "nothing more urgent: the recorded action is next")
        self.assertEqual([t["state"] for t in ws["pending_work"]["open_tickets"]], ["queued"])
        # a new checkpoint without --next: the workspace says none was recorded, and what is out
        self.cv("checkpoint", "--session", "S-1")
        ws = self.fresh()
        self.assertEqual((ws["checkpoint"], ws["turns_since_checkpoint"]), ("cp-2", 0))
        self.assertEqual(ws["next_action"]["basis"], "derived: open tickets, no recorded next action")
        self.assertTrue(all(not d["since_checkpoint"] for d in ws["decisions"]))

    # ---- decisions
    def test_decision_names_its_turn_and_its_predecessor(self):
        self.cv("open", "--session", "S-1", "--topic", "t1", "--question", QUESTION)
        code, out = self.run_tool("conversationalist.py", "decide", "--session", "S-1", "--turn", "u-9",
                                  "--text", "x", ok=False)
        self.assertNotEqual(code, 0)
        self.assertIn("no turn u-9", out)
        u1 = self.say("S-1", "william", "Ship A.")
        code, out = self.run_tool("conversationalist.py", "decide", "--session", "S-1", "--turn", u1,
                                  "--text", "x", "--supersedes", "D-7", ok=False)
        self.assertNotEqual(code, 0)
        self.assertIn("no decision D-7", out)
        self.assertFalse((self.root / "sessions" / "S-1" / "decisions.jsonl").exists(), "nothing was recorded")

    # ---- a pointer that is lost, corrupt or stale
    def test_lost_corrupt_or_stale_pointer_is_rebuilt_from_checkpoints(self):
        r = self.round_one()
        pointer = self.root / "sessions" / "workspace.json"
        good = pointer.read_text(encoding="utf-8")
        want = self.fresh()
        for damage in ("delete", "corrupt", "wrong-session"):
            if damage == "delete":
                pointer.unlink()
            elif damage == "corrupt":
                pointer.write_text("{not json", encoding="utf-8")
            else:
                pointer.write_text(json.dumps({"session": "S-gone", "checkpoint": "cp-1"}), encoding="utf-8")
            ws = self.fresh()
            self.assertEqual(ws["workspace"], "loaded", damage)
            self.assertIn("rebuilt from the newest checkpoint", ws["source"], damage)
            for k in ("session", "checkpoint", "current_topic", "decisions", "pending_work", "next_action"):
                self.assertEqual(ws[k], want[k], f"{damage}: {k}")
        # stale: the pointer names an older checkpoint than the one on disk
        pointer.write_text(good, encoding="utf-8")
        cp2 = self.root / "sessions" / "S-1" / "checkpoints" / "0002.json"
        cp1 = json.loads((self.root / "sessions" / "S-1" / "checkpoints" / "0001.json").read_text(encoding="utf-8"))
        cp2.write_text(json.dumps(dict(cp1, id="cp-2", next_action={"text": "A later plan.", "turn": "u-2"})),
                       encoding="utf-8")
        ws = self.fresh()
        self.assertEqual(ws["checkpoint"], "cp-2")
        self.assertIn("the checkpoint on disk was used", ws["pointer"])
        self.assertEqual(ws["next_action"]["text"], "A later plan.")

    def test_latest_checkpointed_session_is_the_workspace_and_another_can_be_named(self):
        self.round_one("S-1", "t1")
        pointer = self.root / "sessions" / "workspace.json"
        pointer_for_s1 = pointer.read_text(encoding="utf-8")
        self.cv("open", "--session", "S-2", "--topic", "t2", "--question", "A second invented question?")
        u = self.say("S-2", "william", "Park this one.")
        self.cv("decide", "--session", "S-2", "--turn", u, "--text", "Parked until the first topic is done.")
        self.cv("checkpoint", "--session", "S-2", "--next", "Come back after topic one.")
        ws = self.fresh()
        self.assertEqual((ws["session"], ws["current_topic"]["topic"]), ("S-2", "t2"))
        self.assertEqual(ws["next_action"]["text"], "Come back after topic one.")
        other = self.fresh("--session", "S-1")
        self.assertEqual((other["session"], other["current_topic"]["topic"]), ("S-1", "t1"))
        self.assertEqual(other["source"], "session named on the command line")
        self.assertEqual(other["next_action"]["text"], NEXT)
        # a pointer left behind on the older session is not believed: the newest checkpoint decides
        pointer.write_text(pointer_for_s1, encoding="utf-8")
        ws = self.fresh()
        self.assertEqual(ws["session"], "S-2")
        self.assertIn("pointer names session S-1", ws["pointer"])
        self.assertIn("rebuilt from the newest checkpoint", ws["source"])
        # and without any pointer, the same
        pointer.unlink()
        self.assertEqual(self.fresh()["session"], "S-2")

    # ---- nothing to resume
    def test_empty_workspace_says_so(self):
        ws = self.fresh()
        self.assertEqual(ws["workspace"], "empty")
        self.assertIn("no checkpoint in any session", ws["note"])
        self.cv("open", "--session", "S-1", "--topic", "t1", "--question", QUESTION)
        self.say("S-1", "william", "Hello.")
        self.assertEqual(self.fresh()["workspace"], "empty", "a session without a checkpoint is not a workspace yet")
        named = self.fresh("--session", "S-1")
        self.assertEqual(named["workspace"], "empty")
        self.assertIn("open --session S-1", named["note"])
        self.assertIn("workspace: empty", self.run_tool("conversationalist.py", "workspace")[1])
        # a round closed with nothing decided and nothing asked: loaded, and honestly bare
        self.cv("checkpoint", "--session", "S-1")
        ws = self.fresh()
        self.assertEqual((ws["workspace"], ws["decisions"]), ("loaded", []))
        self.assertEqual(ws["next_action"]["basis"], "derived: nothing recorded")
        text = self.run_tool("conversationalist.py", "workspace")[1]
        self.assertIn("decisions       none recorded", text)
        self.assertIn("pending work    none", text)

    # ---- the acknowledgment level is read live; an unreachable remote must not block the load
    def test_workspace_loads_when_the_shared_remote_cannot_be_reached(self):
        if not shutil.which("git"):
            self.skipTest("git is not installed")
        r = self.round_one()

        def git(*args):
            return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True,
                                  encoding="utf-8")
        git("init", "-q")
        git("config", "user.email", "test@example.invalid")
        git("config", "user.name", "test")
        git("add", "workflow")
        self.assertEqual(git("commit", "-q", "-m", "ledger").returncode, 0)
        git("remote", "add", "origin", str(self.root / "no-such-remote.git"))
        ws = self.fresh()
        self.assertEqual(ws["workspace"], "loaded")
        self.assertEqual([(t["receipt"], t["ack"]) for t in ws["pending_work"]["open_tickets"]],
                         [(r["ticket"], "committed")], "committed here; the remote gave no live evidence")
        self.assertEqual(ws["next_action"]["text"], NEXT)

    # ---- private state stays out of git
    def test_workspace_and_sessions_are_ignored_by_git(self):
        if not (REPO / ".git").exists() or not shutil.which("git"):
            self.skipTest("not a git checkout, or git is not installed")
        private = ["sessions/workspace.json", "sessions/S-1/decisions.jsonl", "sessions/S-1/checkpoints/0001.json",
                   "sessions/S-1/turns/0001.jsonl"]
        r = subprocess.run(["git", "check-ignore", *private], cwd=str(REPO), capture_output=True, text=True)
        self.assertEqual(sorted(r.stdout.split()), sorted(private))


if __name__ == "__main__":
    unittest.main()
