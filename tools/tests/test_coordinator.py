"""Phase 1 gate for the Coordinator (LiveOS research through conversation, section 8).

Gate: submit the same request twice, interrupt the worker, restart the Coordinator, and
see one effective result with its provenance. Plus the liveness cases of acceptance
case 5: a dead worker is recovered, a wedged worker is flagged, healthy long work is left
alone, and an idle reconcile changes nothing.

Every step runs the coordinator as a new process against a scratch ledger
(LIVEOS_ROOT), so each call is also a restart: nothing survives except what is on disk.

    python -m unittest tools/tests/test_coordinator.py -v
"""
from pathlib import Path
import datetime as dt, json, os, shutil, subprocess, sys, tempfile, unittest

REPO = Path(__file__).resolve().parents[2]
COORD = REPO / "tools" / "coordinator.py"


class Ledger(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="liveos-test-"))
        (self.root / "workflow").mkdir()
        shutil.copy(REPO / "workflow" / "roster.json", self.root / "workflow" / "roster.json")
        topic = self.root / "topics" / "t1"
        topic.mkdir(parents=True)
        (topic / "index.md").write_text("# test topic\n", encoding="utf-8")
        self.procs = []

    def tearDown(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()
        shutil.rmtree(self.root, ignore_errors=True)

    # ---- helpers
    def co(self, *args, ok=True):
        env = dict(os.environ, LIVEOS_ROOT=str(self.root))
        r = subprocess.run([sys.executable, "-I", str(COORD), *args], env=env,
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        if ok:
            self.assertEqual(r.returncode, 0, f"{args}\n{r.stdout}\n{r.stderr}")
        try:
            return r.returncode, json.loads(r.stdout)
        except Exception:
            return r.returncode, r.stdout + r.stderr

    def submit(self, key="S-01/u-1/q", after=None, kind="research", question="Did X change?"):
        args = ["submit", "--kind", kind, "--question", question,
                "--done-when", "Return old and new values with locators.",
                "--topic", "t1", "--session", "S-01", "--turn", "u-1", "--request-key", key]
        if after:
            args += ["--after-success", after]
        return self.co(*args)[1]

    def worker(self):
        """A stand-in worker process whose life and death the test controls."""
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
        self.procs.append(p)
        return p

    def lease(self, tid):
        return self.root / ".local" / "workflow" / "leases" / f"{tid}.json"

    def age_lease(self, tid, seconds):
        p = self.lease(tid)
        d = json.loads(p.read_text(encoding="utf-8"))
        d["last_progress"] = (dt.datetime.now(dt.timezone.utc)
                              - dt.timedelta(seconds=seconds)).isoformat(timespec="seconds")
        p.write_text(json.dumps(d), encoding="utf-8")

    def tickets(self, kind):
        d = self.root / "workflow" / "outbox" / kind
        return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []

    def state(self, tid):
        return self.co("show", tid)[1]["derived_state"]

    def inbox(self):
        p = self.root / "sessions" / "S-01" / "inbox.jsonl"
        if not p.is_file():
            return []
        return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

    def tree(self):
        out = {}
        for base in ("workflow", "sessions"):
            for p in sorted((self.root / base).rglob("*")):
                if p.is_file():
                    out[str(p.relative_to(self.root))] = p.read_bytes()
        return out

    # ---- the gate
    def test_gate_one_effective_result_with_provenance(self):
        # the same request, twice
        first = self.submit(after="interpret")
        second = self.submit(after="interpret")
        self.assertEqual(first["receipt"], second["receipt"])
        self.assertEqual(second.get("duplicate_of"), first["receipt"])
        self.assertEqual(self.tickets("research"), [first["receipt"]])
        tid = first["receipt"]

        # a worker claims it, then dies without reporting anything
        w1 = self.worker()
        a1 = self.co("claim", "--worker", "research-agent", "--pid", str(w1.pid))[1]
        self.assertEqual(a1["claimed"], tid)
        w1.kill(); w1.wait()

        # the next coordinator run notices the dead worker and requeues
        acts = self.co("reconcile", "--json")[1]
        self.assertEqual([(a["ticket"], a["action"]) for a in acts], [(tid, "requeued")])
        self.assertEqual(self.state(tid)["state"], "queued")

        # the dead attempt cannot publish a late result
        code, _ = self.co("complete", tid, "--attempt-id", a1["attempt_id"],
                          "--summary", "late answer from the dead attempt", ok=False)
        self.assertNotEqual(code, 0)
        self.assertEqual(self.state(tid)["state"], "queued")

        # a second attempt completes
        a2 = self.co("claim", "--worker", "research-agent")[1]
        self.assertNotEqual(a2["attempt_id"], a1["attempt_id"])
        self.co("complete", tid, "--attempt-id", a2["attempt_id"],
                "--summary", "threshold changed from 5m to 8m", "--sources", "S:amend-2 s.4")
        # a duplicate completion is ignored, not applied twice
        self.assertEqual(self.co("complete", tid, "--attempt-id", a2["attempt_id"],
                                 "--summary", "again")[1]["already"], "completed")

        # the follow-on interpretation is created exactly once, however often we reconcile
        self.co("reconcile"); self.co("reconcile"); self.co("reconcile")
        children = self.tickets("interpret")
        self.assertEqual(len(children), 1)
        self.assertEqual(self.inbox(), [], "research with a follow-on is not delivered on its own")

        # the interpreter finishes; the result reaches the session once
        ia = self.co("claim", "--worker", "interpreter", "--kind", "interpret")[1]
        self.co("complete", children[0], "--attempt-id", ia["attempt_id"],
                "--summary", "threshold in the diagram changes; approval vs remedy still holds",
                "--claims", "C-12")
        self.co("reconcile"); self.co("reconcile")
        box = self.inbox()
        self.assertEqual(len(box), 1)

        # provenance: the update names the original question and how it was produced
        item = box[0]
        self.assertEqual(item["answers"], tid)
        self.assertEqual(item["asked"], "Did X change?")
        self.assertEqual(item["origin"], {"session": "S-01", "turn": "u-1", "round": 1})
        self.assertEqual(item["result"]["claim_ids_changed"], ["C-12"])
        for field in ("question_revision", "input_revision", "output_revision"):
            self.assertIn(field, item["result"])
        events = self.co("show", tid)[1]["events"]
        self.assertEqual([e["event"] for e in events],
                         ["created", "claimed", "requeued", "claimed", "completed", "child_created"])
        done = [e for e in events if e["event"] == "completed"][0]
        self.assertEqual(done["attempt_id"], a2["attempt_id"])
        self.assertEqual(done["attempt"], 2)

    # ---- liveness without noise
    def test_wedged_worker_is_flagged_and_healthy_worker_is_left_alone(self):
        wedged = self.submit(key="k-wedged")["receipt"]
        healthy = self.submit(key="k-healthy")["receipt"]
        w1, w2 = self.worker(), self.worker()
        self.co("claim", "--worker", "research-agent", "--pid", str(w1.pid))
        self.co("claim", "--worker", "research-agent", "--pid", str(w2.pid))
        self.age_lease(wedged, 20 * 60)       # alive, silent for 20 minutes
        self.co("progress", healthy, "--milestone", "reading source 3 of 9")

        acts = self.co("reconcile", "--json")[1]
        self.assertEqual([(a["ticket"], a["action"]) for a in acts], [(wedged, "flagged-stalled")])
        self.assertEqual(self.state(wedged)["state"], "claimed", "flagged, not killed")
        self.assertEqual(self.state(healthy)["state"], "claimed")
        self.assertEqual(self.co("reconcile", "--json")[1], [], "flagged once per attempt")
        code, rows = self.co("status", "--json")
        self.assertEqual({r["id"]: r["state"] for r in rows}, {wedged: "stalled", healthy: "claimed"})

        # past the lease, the wedged ticket goes back to the queue
        self.age_lease(wedged, 40 * 60)
        acts = self.co("reconcile", "--json")[1]
        self.assertEqual([(a["ticket"], a["action"]) for a in acts], [(wedged, "requeued")])

    def test_agent_worker_without_a_process_is_not_declared_dead(self):
        tid = self.submit()["receipt"]
        self.co("claim", "--worker", "research-agent")     # no pid, no run id
        self.assertEqual(self.co("reconcile", "--json")[1], [])
        self.assertEqual(self.state(tid)["state"], "claimed")

    def test_exhausted_attempts_route_to_one_diagnose_ticket(self):
        tid = self.submit()["receipt"]
        for _ in range(3):
            self.co("claim", "--worker", "research-agent")
            self.age_lease(tid, 40 * 60)
            self.co("reconcile")
        self.assertEqual(self.state(tid)["state"], "failed")
        self.co("reconcile"); self.co("reconcile")
        self.assertEqual(len(self.tickets("diagnose")), 1)
        box = self.inbox()
        self.assertEqual(len(box), 1)
        self.assertEqual(box[0]["result"]["next_action"], "diagnose")

    def test_idle_reconcile_changes_nothing(self):
        self.submit()
        before = self.tree()
        code, out = self.co("reconcile")
        self.assertIn("nothing to reconcile", out)
        self.assertEqual(self.tree(), before)

    # ---- timing: the immediate event, and the minute check as a service
    def test_completion_routes_at_once_without_waiting_for_the_minute_check(self):
        tid = self.submit(after="interpret")["receipt"]
        a = self.co("claim", "--worker", "research-agent")[1]
        self.co("complete", tid, "--attempt-id", a["attempt_id"], "--summary", "found it")
        self.assertEqual(len(self.tickets("interpret")), 1, "follow-on queued by the completion itself")
        ia = self.co("claim", "--worker", "interpreter", "--kind", "interpret")[1]
        self.co("complete", self.tickets("interpret")[0], "--attempt-id", ia["attempt_id"],
                "--summary", "conclusion holds")
        self.assertEqual(len(self.inbox()), 1, "delivered by the completion itself")

    def test_service_tick_recovers_a_missed_event_and_leaves_a_heartbeat(self):
        tid = self.submit()["receipt"]
        w = self.worker()
        self.co("claim", "--worker", "research-agent", "--pid", str(w.pid))
        w.kill(); w.wait()                       # nobody reports this; only the tick can find it
        code, out = self.co("serve", "--once", "--interval", "60")
        self.assertIn("action=requeued", out)
        self.assertEqual(self.state(tid)["state"], "queued")
        hb = json.loads((self.root / ".local" / "workflow" / "coordinator.json").read_text(encoding="utf-8"))
        self.assertEqual(hb["ticks"], 1)
        self.assertIsNone(hb["last_error"])
        # an idle tick touches runtime state only: the ledger is byte-identical
        before = self.tree()
        self.co("serve", "--once")
        self.assertEqual(self.tree(), before)
        # the one-shot service has exited, and status says so plainly
        code, text = self.co("status")
        self.assertIn("coordinator service: stopped", text)

    # ---- scope and roster
    def test_missing_topic_index_is_refused(self):
        code, out = self.co("submit", "--kind", "research", "--question", "q",
                            "--done-when", "d", "--topic", "no-such-topic", ok=False)
        self.assertNotEqual(code, 0)
        self.assertIn("scope_ref does not exist", out)
        self.assertEqual(self.tickets("research"), [])

    def test_worker_must_advertise_the_capability(self):
        self.submit()
        code, out = self.co("claim", "--worker", "report-writer", ok=False)
        self.assertNotEqual(code, 0)
        self.assertIn("does not advertise", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
