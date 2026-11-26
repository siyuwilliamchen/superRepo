"""The independent watchdog (LiveOS research through conversation, section 4 and acceptance
case 5, "liveness without noise").

Each case runs the watchdog and the Coordinator as new processes against a scratch root
(LIVEOS_ROOT), so nothing survives between calls except what is on disk. Stand-in processes
play the Coordinator service, a relay and a worker; the test kills them to make them dead.

    python -m unittest tools/tests/test_watchdog.py -v
"""
from pathlib import Path
import datetime as dt, json, os, shutil, subprocess, sys, tempfile, unittest

REPO = Path(__file__).resolve().parents[2]
COORD = REPO / "tools" / "coordinator.py"
WATCHDOG = REPO / "tools" / "watchdog.py"


def utc_ago(seconds):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=seconds)).isoformat(timespec="seconds")


class Watchdog(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="liveos-wd-test-"))
        (self.root / "workflow").mkdir()
        shutil.copy(REPO / "workflow" / "roster.json", self.root / "workflow" / "roster.json")
        shutil.copy(REPO / "workflow" / "deadlines.json", self.root / "workflow" / "deadlines.json")
        topic = self.root / "topics" / "t1"
        topic.mkdir(parents=True)
        (topic / "index.md").write_text("# test topic\n", encoding="utf-8")
        self.runtime = self.root / ".local" / "workflow"
        self.runtime.mkdir(parents=True)
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()
        shutil.rmtree(self.root, ignore_errors=True)

    # ---- helpers
    def run_tool(self, tool, *args, ok=True):
        env = dict(os.environ, LIVEOS_ROOT=str(self.root))
        r = subprocess.run([sys.executable, "-I", str(tool), *args], env=env,
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        if ok:
            self.assertEqual(r.returncode, 0, f"{args}\n{r.stdout}\n{r.stderr}")
        try:
            return r.returncode, json.loads(r.stdout)
        except Exception:
            return r.returncode, r.stdout + r.stderr

    def co(self, *args, ok=True):
        return self.run_tool(COORD, *args, ok=ok)

    def wd(self, *args, ok=False):
        """One watchdog tick as JSON. Exit code is part of what the tests check, so ok=False."""
        return self.run_tool(WATCHDOG, "serve", "--once", "--json", *args, ok=ok)

    def submit(self, key="S-01/u-1/q", kind="research", question="Did X change?"):
        return self.co("submit", "--kind", kind, "--question", question,
                       "--done-when", "Return old and new values with locators.",
                       "--topic", "t1", "--session", "S-01", "--turn", "u-1", "--request-key", key)[1]

    def process(self):
        """A stand-in process whose life and death the test controls."""
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
        self.procs.append(p)
        return p

    def dead_pid(self):
        p = self.process()
        p.kill(); p.wait()
        return p.pid

    def tickets(self, kind):
        d = self.root / "workflow" / "outbox" / kind
        return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []

    def state(self, tid):
        return self.co("show", tid)[1]["derived_state"]

    def heartbeat(self):
        return json.loads((self.runtime / "watchdog.json").read_text(encoding="utf-8"))

    def findings(self, hb, check):
        return [f for f in hb["findings"] if f["check"] == check]

    def tree(self, *bases):
        out = {}
        for base in bases:
            d = self.root / base
            if not d.is_dir():
                continue
            for p in sorted(d.rglob("*")):
                if p.is_file():
                    out[str(p.relative_to(self.root))] = p.read_bytes()
        return out

    # ---- the coordinator service
    def test_dead_coordinator_service_is_detected_and_reconcile_runs_in_its_place(self):
        tid = self.submit()["receipt"]
        worker = self.process()
        self.co("claim", "--worker", "research-agent", "--pid", str(worker.pid))
        worker.kill(); worker.wait()             # a dead worker nobody reports

        # the service's heartbeat says it is alive at a pid that is gone
        (self.runtime / "coordinator.json").write_text(json.dumps(
            {"pid": self.dead_pid(), "at": utc_ago(30), "ticks": 12, "interval": 60, "last_error": None}),
            encoding="utf-8")

        code, hb = self.wd()
        svc = self.findings(hb, "coordinator-service")
        self.assertEqual(len(svc), 1)
        self.assertEqual(svc[0]["status"], "dead")
        self.assertIn("not alive", svc[0]["why"])
        self.assertIn("ran reconcile in its place: 1 action", svc[0]["did"])
        # the watchdog did not write the ledger itself: the requeue is the Coordinator's own event
        self.assertEqual([(a["by"], a["ticket"], a["action"]) for a in hb["actions"]],
                         [("reconcile", tid, "requeued")])
        self.assertEqual(self.state(tid)["state"], "queued")
        self.assertEqual(code, 1, "something needed attention")
        self.assertEqual(hb["ticks"], 1)

    def test_late_coordinator_heartbeat_is_reported_as_late(self):
        self.submit()
        keeper = self.process()                  # alive, but its heartbeat is stale
        (self.runtime / "coordinator.json").write_text(json.dumps(
            {"pid": keeper.pid, "at": utc_ago(10 * 60), "ticks": 3, "interval": 60, "last_error": None}),
            encoding="utf-8")
        code, hb = self.wd()
        svc = self.findings(hb, "coordinator-service")
        self.assertEqual(svc[0]["status"], "late")
        self.assertEqual(svc[0]["did"], "ran reconcile in its place: 0 action(s)")
        self.assertEqual(hb["actions"], [], "an idle reconcile changes nothing")

    # ---- relays
    def test_dead_relay_heartbeat_is_detected(self):
        session = "S-01"
        sdir = self.root / "sessions" / session
        sdir.mkdir(parents=True)
        (sdir / "session.json").write_text(json.dumps(
            {"id": session, "notify": {"kind": "file", "path": str(self.root / "chat.jsonl")}}), encoding="utf-8")
        (sdir / "inbox.jsonl").write_text(json.dumps({"ticket": "T-0001", "read": False}) + "\n", encoding="utf-8")
        (self.runtime / "relays").mkdir()
        (self.runtime / "relays" / f"{session}.json").write_text(json.dumps(
            {"pid": self.dead_pid(), "at": utc_ago(4), "ticks": 100, "interval": 2.0, "notified": 1,
             "session": session}), encoding="utf-8")

        code, hb = self.wd()
        relays = self.findings(hb, "relay")
        self.assertEqual(len(relays), 1)
        self.assertEqual(relays[0]["subject"], session)
        self.assertEqual(relays[0]["status"], "dead")
        self.assertEqual(relays[0]["unread_results"], 1)
        self.assertTrue(relays[0]["attention"])
        self.assertIn("conversationalist.py relay --session S-01", relays[0]["next"])
        self.assertEqual(code, 1)

    def test_live_relay_is_left_alone(self):
        relay = self.process()
        (self.runtime / "relays").mkdir()
        (self.runtime / "relays" / "S-02.json").write_text(json.dumps(
            {"pid": relay.pid, "at": utc_ago(1), "ticks": 5, "interval": 2.0, "notified": 0, "session": "S-02"}),
            encoding="utf-8")
        code, hb = self.wd()
        self.assertEqual(self.findings(hb, "relay"), [])
        self.assertEqual(code, 0)

    # ---- run.py jobs
    def test_interrupted_run_job_is_reported_with_its_resume_command(self):
        runs = self.root / ".local" / "runs"
        runs.mkdir(parents=True)
        (runs / "20261125-000000-census.json").write_text(json.dumps(
            {"id": "20261125-000000-census", "name": "census", "state": "running",
             "pid": self.dead_pid(), "child_pid": None,
             "heartbeat": utc_ago(600), "last_progress": utc_ago(600), "started": utc_ago(900),
             "resume": "python tools/run.py start census -- python tools/vault_census.py",
             "log": ".local/runs/20261125-000000-census.log"}), encoding="utf-8")
        code, hb = self.wd()
        runs_found = self.findings(hb, "run")
        self.assertEqual(len(runs_found), 1)
        self.assertEqual(runs_found[0]["status"], "interrupted")
        self.assertEqual(runs_found[0]["next"], "python tools/run.py start census -- python tools/vault_census.py")

    # ---- capability-specific deadlines
    def test_ticket_past_its_kinds_deadline_is_escalated_once(self):
        tid = self.submit()["receipt"]
        worker = self.process()
        a = self.co("claim", "--worker", "research-agent", "--pid", str(worker.pid))[1]
        # the worker is alive and keeps reporting progress (so the Coordinator sees nothing wrong),
        # but the attempt began three hours ago; the research deadline is 90 minutes
        ev = next((self.root / "workflow" / "events" / tid).glob("*-claimed.json"))
        rec = json.loads(ev.read_text(encoding="utf-8"))
        rec["at"] = utc_ago(3 * 3600)
        ev.write_text(json.dumps(rec), encoding="utf-8")
        self.co("progress", tid, "--attempt-id", a["attempt_id"], "--milestone", "searching again")

        code, hb = self.wd()
        dl = self.findings(hb, "deadline")
        self.assertEqual(len(dl), 1)
        self.assertEqual(dl[0]["subject"], tid)
        self.assertEqual(dl[0]["status"], "overdue")
        self.assertEqual(dl[0]["kind"], "research")
        self.assertEqual(dl[0]["deadline"], "1h30")
        self.assertIn("90 minutes", dl[0]["why"], "the reason comes from workflow/deadlines.json")
        diag = self.tickets("diagnose")
        self.assertEqual(len(diag), 1)
        self.assertEqual(dl[0]["diagnose"], diag[0])
        self.assertEqual(dl[0]["request_key"], f"watchdog:deadline:{tid}#a1")
        self.assertEqual(code, 1)
        # the overdue ticket itself is untouched: still claimed by the same attempt
        self.assertEqual(self.state(tid)["state"], "claimed")
        self.assertEqual([e["event"] for e in self.co("show", tid)[1]["events"]], ["created", "claimed"])
        # the diagnose ticket went through the Coordinator: it has a created event and names the session
        d = self.co("show", diag[0])[1]
        self.assertEqual(d["ticket"]["from"], "watchdog")
        self.assertEqual(d["ticket"]["return_to"]["session"], "S-01")
        self.assertEqual([e["event"] for e in d["events"]], ["created"])

        # repeated ticks: still one diagnose ticket, and the finding says so
        before = self.tree("workflow")
        for _ in range(3):
            code, hb2 = self.wd()
        self.assertEqual(self.tickets("diagnose"), diag)
        self.assertIn("already escalated", self.findings(hb2, "deadline")[0]["did"])
        self.assertEqual(self.tree("workflow"), before, "nothing written to the ledger after the one escalation")

        # even with its own memory wiped, the deterministic request key keeps it to one ticket
        (self.runtime / "watchdog.json").unlink()
        code, hb3 = self.wd()
        self.assertEqual(self.tickets("diagnose"), diag)
        self.assertIn("already existed", self.findings(hb3, "deadline")[0]["did"])

    def test_healthy_long_job_within_deadline_is_left_alone(self):
        tid = self.submit(kind="build", key="k-build")["receipt"]
        worker = self.process()
        a = self.co("claim", "--worker", "developer", "--pid", str(worker.pid))[1]
        ev = next((self.root / "workflow" / "events" / tid).glob("*-claimed.json"))
        rec = json.loads(ev.read_text(encoding="utf-8"))
        rec["at"] = utc_ago(2 * 3600)             # two hours into a six-hour build deadline
        ev.write_text(json.dumps(rec), encoding="utf-8")
        self.co("progress", tid, "--attempt-id", a["attempt_id"], "--milestone", "tests passing, writing method")
        # a healthy coordinator service is also running
        svc = self.process()
        (self.runtime / "coordinator.json").write_text(json.dumps(
            {"pid": svc.pid, "at": utc_ago(5), "ticks": 400, "interval": 60, "last_error": None}), encoding="utf-8")

        before = self.tree("workflow", "sessions")
        code, hb = self.wd()
        self.assertEqual(code, 0)
        self.assertEqual(hb["findings"], [])
        self.assertEqual(hb["actions"], [])
        self.assertEqual(self.tickets("diagnose"), [])
        self.assertEqual(self.state(tid)["state"], "claimed")
        self.assertEqual(self.tree("workflow", "sessions"), before)

    # ---- an idle tick
    def test_idle_tick_leaves_workflow_byte_identical_and_touches_only_runtime_state(self):
        self.submit()
        before = self.tree("workflow", "sessions", "topics")
        runtime_before = self.tree(".local")
        code, hb = self.wd()
        self.assertEqual(code, 0)
        self.assertEqual(hb["findings"], [])
        self.assertEqual(self.tree("workflow", "sessions", "topics"), before)
        runtime_after = self.tree(".local")
        new_files = set(runtime_after) - set(runtime_before)
        self.assertEqual(new_files, {str(Path(".local") / "workflow" / "watchdog.json")},
                         "the only new file is the watchdog's own heartbeat (no log line for a quiet tick)")
        # a second idle tick: the ledger still byte-identical, the heartbeat counts up
        code, hb2 = self.wd()
        self.assertEqual(self.tree("workflow", "sessions", "topics"), before)
        self.assertEqual(hb2["ticks"], 2)
        self.assertEqual(self.heartbeat()["ticks"], 2)

    # ---- views
    def test_status_and_deadlines_views(self):
        code, out = self.run_tool(WATCHDOG, "status", ok=False)
        self.assertEqual(code, 1)
        self.assertIn("never run", out)
        self.wd()
        code, out = self.run_tool(WATCHDOG, "status")
        self.assertIn("watchdog: not running; last tick", out)
        code, out = self.run_tool(WATCHDOG, "deadlines")
        for kind in ("research", "interpret", "write", "diagnose", "build"):
            self.assertIn(kind, out)
        self.assertIn("workflow", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
