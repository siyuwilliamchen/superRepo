"""Gate for local usage accounting (tools/usage.py; method in system/methods/usage.md).

What must hold:

- one provider response is counted once per run, however many lines a host wrote for it and
  however many captures of the run were ingested; the same response id in another run is another
  response;
- input, output, cache-read and cache-write counts are kept apart, and a final count replaces a
  live snapshot of the same response;
- child and parent totals are separate, and add up to the host's own total for the run;
- role, stage and outcome come from a declaration, the workflow ledger or the capture, in that
  order, and an undeclared one is reported as unknown, not guessed;
- aggregate figures and per-process averages say how many values they hold and how many they lack;
- a count the host did not report is unavailable (null, "n/a"), never zero;
- nothing a worker read or wrote reaches the usage store, and the store is ignored by git.

Every fixture is synthetic (tools/tests/fixtures/usage/make_fixtures.py); no real session is
read. Each call runs the tool as a new process against a scratch root (LIVEOS_ROOT).

    python -m unittest tools/tests/test_usage.py -v
"""
from pathlib import Path
import json, os, shutil, subprocess, sys, tempfile, unittest

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools"
FIX = TOOLS / "tests" / "fixtures" / "usage"
RUN = "syn-session-0001"
STREAM = FIX / "claude_stream_parent_child.jsonl"
TRANSCRIPT = FIX / "claude_transcript" / "syn-session-0001.jsonl"
MARKER = "SYNTHETIC-REPLY-TEXT"


class Usage(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="liveos-usage-"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def tool(self, name, *args, ok=True):
        env = dict(os.environ, LIVEOS_ROOT=str(self.root))
        r = subprocess.run([sys.executable, "-I", str(TOOLS / name), *map(str, args)], env=env,
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        if ok:
            self.assertEqual(r.returncode, 0, f"{name} {args}\n{r.stdout}\n{r.stderr}")
        try:
            return r.returncode, json.loads(r.stdout)
        except Exception:
            return r.returncode, r.stdout + r.stderr

    def us(self, *args, **kw):
        return self.tool("usage.py", *args, **kw)[1]

    def report(self, *args):
        return self.us("report", "--json", *args)

    def proc(self, rep, key):
        return next(p for p in rep["processes"] if p["process"] == key)

    def counts(self, tokens):
        return [tokens[c] for c in ("input", "output", "cache_read", "cache_write")]

    def sums(self, group):
        return [group["tokens"][c]["sum"] for c in ("input", "output", "cache_read", "cache_write")]

    # ---- one response, once
    def test_one_response_counted_once_per_run_across_lines_and_sources(self):
        self.us("ingest", "--format", "claude-stream", STREAM)
        self.us("ingest", "--format", "claude-transcript", TRANSCRIPT)
        rep = self.report()
        # 4 stream lines + 5 transcript lines for 3 provider responses
        self.assertEqual(rep["response_lines_read"], 9)
        self.assertEqual(rep["responses_counted"], 3)
        self.assertEqual(rep["runs"][0]["duplicate_lines_dropped"], 6)
        # ingesting both captures again changes no figure
        before = {p["process"]: p["tokens"] for p in rep["processes"]}
        self.us("ingest", "--format", "claude-stream", STREAM)
        self.us("ingest", "--format", "claude-transcript", TRANSCRIPT)
        again = self.report()
        self.assertEqual(again["responses_counted"], 3)
        self.assertEqual({p["process"]: p["tokens"] for p in again["processes"]}, before)
        # the host's placeholder message is not a provider response
        ids = [r["response_id"] for r in self.us("show", "--run", RUN)["responses"]]
        self.assertEqual(sorted(ids), ["msg_SYN_C1", "msg_SYN_P1", "msg_SYN_P2"])

    def test_same_response_id_in_another_run_is_another_response(self):
        self.us("ingest", "--format", "claude-transcript", TRANSCRIPT)
        self.us("ingest", "--format", "claude-transcript", TRANSCRIPT, "--run-id", "syn-session-0002")
        rep = self.report()
        self.assertEqual(rep["responses_counted"], 6)
        self.assertEqual(self.sums(rep["totals"]["all"]), [58, 320, 1000, 1040])
        one = self.report("--run", RUN)
        self.assertEqual(self.sums(one["totals"]["all"]), [29, 160, 500, 520])

    # ---- categories, and a final count replacing a live snapshot
    def test_final_counts_replace_live_snapshots(self):
        self.us("ingest", "--format", "claude-stream", STREAM)
        rep = self.report()
        parent, child = self.proc(rep, f"{RUN}/main"), self.proc(rep, f"{RUN}/agentSYN1")
        # stream only: the parent's figures are the host's exact turn totals; the child's output
        # is a live snapshot and is reported as a lower bound, not as the count
        self.assertEqual(parent["basis"], "host_turn_totals")
        self.assertEqual(self.counts(parent["tokens"]), [22, 130, 500, 120])
        self.assertEqual(child["basis"], "responses_partial")
        self.assertTrue(child["output_lower_bound"])
        self.assertEqual(self.counts(child["tokens"]), [7, 9, 0, 400])
        self.assertTrue(rep["totals"]["child"]["tokens"]["output"]["lower_bound"])
        self.assertFalse(rep["totals"]["parent"]["tokens"]["output"]["lower_bound"])
        self.assertEqual(rep["runs"][0]["verdict"], "partly checked")
        self.assertTrue(any(u["process"].endswith("/agentSYN1") and u["field"] == "tokens.output"
                            for u in rep["unknown"]))
        text = self.tool("usage.py", "report")[1]
        self.assertIn(">=9", text)

        # the saved session arrives: final counts replace the snapshots, and the books close
        self.us("ingest", "--format", "claude-transcript", TRANSCRIPT)
        rep = self.report()
        parent, child = self.proc(rep, f"{RUN}/main"), self.proc(rep, f"{RUN}/agentSYN1")
        self.assertEqual(parent["basis"], "responses")
        self.assertEqual(self.counts(parent["tokens"]), [22, 130, 500, 120])
        self.assertEqual(child["basis"], "responses")
        self.assertFalse(child["output_lower_bound"])
        self.assertEqual(self.counts(child["tokens"]), [7, 30, 0, 400])
        self.assertEqual(child["tokens"]["total"], 437)
        self.assertEqual(rep["runs"][0]["verdict"], "reconciled")
        self.assertFalse(any(u["field"] == "tokens.output" for u in rep["unknown"]))
        merged = {r["response_id"]: r for r in self.us("show", "--run", RUN)["responses"]}
        self.assertEqual(merged["msg_SYN_P2"]["sources"], ["claude-stream", "claude-transcript"])
        self.assertTrue(merged["msg_SYN_P2"]["final"])
        self.assertEqual(merged["msg_SYN_P2"]["tokens"]["output"], 80)

    # ---- child against parent
    def test_child_and_parent_totals_add_up_to_the_host_total(self):
        self.us("ingest", "--format", "claude-stream", STREAM)
        self.us("ingest", "--format", "claude-transcript", TRANSCRIPT)
        rep = self.report()
        child = self.proc(rep, f"{RUN}/agentSYN1")
        self.assertEqual(child["relation"], "child")
        self.assertEqual(child["parent"], f"{RUN}/main")
        self.assertEqual(self.proc(rep, f"{RUN}/main")["relation"], "parent")
        self.assertEqual(self.sums(rep["totals"]["parent"]), [22, 130, 500, 120])
        self.assertEqual(self.sums(rep["totals"]["child"]), [7, 30, 0, 400])
        self.assertEqual(self.sums(rep["totals"]["all"]), [29, 160, 500, 520])
        checks = rep["runs"][0]["checks"]
        run_check = next(c for c in checks if c["scope"] == "run")
        self.assertEqual({k: (v["accounted"], v["host"], v["verdict"]) for k, v in run_check["by_category"].items()},
                         {"input": (29, 29, "reconciled"), "output": (160, 160, "reconciled"),
                          "cache_read": (500, 500, "reconciled"), "cache_write": (520, 520, "reconciled")})
        child_sum = next(c for c in checks if c.get("agent_id") == "agentSYN1")
        self.assertEqual(child_sum["by_category"]["total"]["verdict"], "reconciled")
        # a worker started as its own process by another run is a child across runs
        self.us("ingest", "--format", "codex-events", FIX / "codex_events.jsonl",
                "--parent", f"{RUN}/main", "--role", "verifier", "--stage", "verify")
        rep = self.report()
        worker = self.proc(rep, "syn-thread-0001/main")
        self.assertEqual((worker["relation"], worker["parent"]), ("child", f"{RUN}/main"))
        self.assertEqual(rep["totals"]["child"]["processes"], 2)
        self.assertEqual(self.sums(rep["totals"]["child"]), [407, 45, 600, 400])

    # ---- role, stage, outcome
    def test_role_stage_outcome_declared_observed_or_unknown(self):
        self.us("ingest", "--format", "claude-stream", STREAM)
        self.us("ingest", "--format", "claude-transcript", TRANSCRIPT)
        rep = self.report()
        parent, child = self.proc(rep, f"{RUN}/main"), self.proc(rep, f"{RUN}/agentSYN1")
        # nothing declared: the child's role is the agent type the host named; the rest is unknown
        self.assertEqual((child["role"], child["role_basis"]), ("research-agent", "observed:agent_type"))
        self.assertEqual(child["outcome"], "completed")
        self.assertEqual(child["stage"], "(unknown)")
        self.assertEqual((parent["role"], parent["stage"], parent["outcome"]), ("(unknown)", "(unknown)", "completed"))
        self.assertTrue(any(u["process"] == f"{RUN}/main" and u["field"] == "role" for u in rep["unknown"]))
        self.assertIn("(unknown)", rep["by_stage"])

        self.us("declare", "--run", RUN, "--role", "conversationalist", "--stage", "dispatch")
        self.us("declare", "--run", RUN, "--agent", "agentSYN1", "--stage", "research", "--outcome", "failed")
        rep = self.report()
        parent, child = self.proc(rep, f"{RUN}/main"), self.proc(rep, f"{RUN}/agentSYN1")
        self.assertEqual((parent["role"], parent["role_basis"], parent["stage"]),
                         ("conversationalist", "declared", "dispatch"))
        self.assertEqual((child["stage"], child["outcome"]), ("research", "failed"), "a declaration outranks the capture")
        self.assertEqual(self.sums(rep["by_role"]["conversationalist"]), [22, 130, 500, 120])
        self.assertEqual(self.sums(rep["by_role"]["research-agent"]), [7, 30, 0, 400])
        self.assertEqual(self.sums(rep["by_stage"]["research"]), [7, 30, 0, 400])
        self.assertEqual(sorted(rep["by_outcome"]), ["completed", "failed"])
        self.assertEqual(self.sums(rep["by_outcome"]["failed"]), [7, 30, 0, 400])
        # ingesting the capture again does not undo a declaration
        self.us("ingest", "--format", "claude-stream", STREAM)
        self.assertEqual(self.proc(self.report(), f"{RUN}/agentSYN1")["outcome"], "failed")

    def test_ticket_gives_stage_role_and_outcome_from_the_ledger(self):
        (self.root / "workflow").mkdir()
        shutil.copy(REPO / "workflow" / "roster.json", self.root / "workflow" / "roster.json")
        (self.root / "topics" / "t1").mkdir(parents=True)
        (self.root / "topics" / "t1" / "index.md").write_text("# test topic\n", encoding="utf-8")
        co = lambda *a: self.tool("coordinator.py", *a)[1]
        tid = co("submit", "--kind", "research", "--question", "q", "--done-when", "d", "--topic", "t1")["receipt"]
        attempt = co("claim", "--worker", "research-agent", "--kind", "research")["attempt_id"]
        self.us("ingest", "--format", "codex-events", FIX / "codex_events.jsonl", "--ticket", tid)
        p = self.proc(self.report(), "syn-thread-0001/main")
        self.assertEqual((p["stage"], p["role"], p["role_basis"]), ("research", "research-agent", "ticket"))
        self.assertEqual(p["outcome"], "completed", "the capture's own outcome while the ticket is open")
        co("fail", tid, "--attempt-id", attempt, "--reason", "no source")
        p = self.proc(self.report(), "syn-thread-0001/main")
        self.assertEqual(p["outcome"], "failed", "a terminal ticket state outranks the capture")
        # the accounting only read the ledger
        self.assertEqual(sorted(x.name for x in (self.root / "workflow" / "events" / tid).glob("*.json")),
                         ["0000-created.json", "0001-claimed.json", "0002-failed.json"])

    # ---- unavailable is not zero
    def test_unavailable_is_not_zero(self):
        self.us("ingest", "--format", "codex-events", FIX / "codex_events.jsonl")             # cache_write: 0
        self.us("ingest", "--format", "codex-events", FIX / "codex_events_no_cache_write.jsonl")  # key absent
        self.us("declare", "--run", "never-reported", "--role", "writer", "--stage", "write")  # no capture at all
        rep = self.report()
        zero = self.proc(rep, "syn-thread-0001/main")["tokens"]
        missing = self.proc(rep, "syn-thread-0002/main")["tokens"]
        silent = self.proc(rep, "never-reported/main")
        self.assertEqual(zero["cache_write"], 0)
        self.assertIsNone(missing["cache_write"])
        self.assertEqual(missing["cache_read"], 0, "reported as zero, so zero")
        self.assertIsNone(missing["total"], "a total with a missing part is not a total")
        self.assertEqual(silent["basis"], "unavailable")
        self.assertEqual(self.counts(silent["tokens"]), [None, None, None, None])
        # sums: over what is known, with the gaps counted beside them
        cw = rep["totals"]["all"]["tokens"]["cache_write"]
        self.assertEqual((cw["sum"], cw["known"], cw["unavailable"]), (0, 1, 2))
        inp = rep["totals"]["all"]["tokens"]["input"]
        self.assertEqual((inp["sum"], inp["known"], inp["unavailable"]), (900, 2, 1))
        only_silent = rep["by_role"]["writer"]["tokens"]["input"]
        self.assertEqual((only_silent["sum"], only_silent["known"], only_silent["unavailable"]), (None, 0, 1))
        # averages: the mean of the processes that have the value
        avg = rep["averages_per_process"]["all"]
        self.assertEqual((avg["input"]["mean"], avg["input"]["processes"], avg["input"]["unavailable"]), (450.0, 2, 1))
        self.assertEqual((avg["cache_write"]["mean"], avg["cache_write"]["processes"],
                          avg["cache_write"]["unavailable"]), (0.0, 1, 2))
        self.assertEqual(rep["averages_per_process"]["child"]["input"],
                         {"mean": None, "processes": 0, "unavailable": 0, "lower_bound": False})
        fields = {(u["process"], u["field"]) for u in rep["unknown"]}
        self.assertIn(("syn-thread-0002/main", "tokens.cache_write"), fields)
        self.assertIn(("never-reported/main", "tokens.input"), fields)
        self.assertNotIn(("syn-thread-0001/main", "tokens.cache_write"), fields)
        text = self.tool("usage.py", "report")[1]
        row = next(l for l in text.splitlines() if l.startswith("never-reported/main"))
        self.assertEqual(row.count("n/a"), 4)
        self.assertIn("value(s) unavailable", text)

    # ---- aggregate and per-process averages
    def test_aggregate_and_per_process_averages(self):
        self.us("ingest", "--format", "claude-stream", STREAM)
        self.us("ingest", "--format", "claude-transcript", TRANSCRIPT)
        self.us("ingest", "--format", "codex-session", FIX / "codex_session.jsonl")
        rep = self.report()
        self.assertEqual(rep["totals"]["all"]["processes"], 3)
        self.assertEqual(self.sums(rep["totals"]["all"]), [429, 175, 1100, 520])
        avg = rep["averages_per_process"]
        self.assertEqual([avg["all"][c]["mean"] for c in ("input", "output", "cache_read", "cache_write")],
                         [143.0, 58.3, 366.7, 173.3])
        self.assertEqual([avg["parent"][c]["mean"] for c in ("input", "output", "cache_read", "cache_write")],
                         [211.0, 72.5, 550.0, 60.0])
        self.assertEqual([avg["child"][c]["mean"] for c in ("input", "output", "cache_read", "cache_write")],
                         [7.0, 30.0, 0.0, 400.0])
        self.assertEqual(avg["all"]["total"]["mean"], round((772 + 437 + 1015) / 3, 1))

    # ---- Codex: response ids from the session file, turn totals as the check
    def test_codex_session_and_events_of_one_run(self):
        self.us("ingest", "--format", "codex-events", FIX / "codex_events.jsonl")
        p = self.proc(self.report(), "syn-thread-0001/main")
        self.assertEqual(p["basis"], "host_turn_totals")
        self.assertEqual(self.counts(p["tokens"]), [400, 15, 600, 0], "uncached input is input minus cached")
        self.assertEqual(p["outcome"], "completed")
        self.us("ingest", "--format", "codex-session", FIX / "codex_session.jsonl")
        rep = self.report()
        p = self.proc(rep, "syn-thread-0001/main")
        self.assertEqual((p["basis"], p["responses"]), ("responses", 2))
        self.assertEqual(self.counts(p["tokens"]), [400, 15, 600, 0], "the turn total is a check, not added on top")
        self.assertEqual(rep["runs"][0]["verdict"], "reconciled")
        self.assertEqual(p["model_host"], "synth-gpt-small-1")
        self.assertEqual(p["models_reported"], [])
        self.assertTrue(any(u["field"] == "model_reported" for u in rep["unknown"]))
        self.us("ingest", "--format", "codex-events", FIX / "codex_events_failed.jsonl")
        self.assertEqual(self.proc(self.report(), "syn-thread-0003/main")["outcome"], "failed")

    # ---- privacy
    def test_no_conversation_text_reaches_the_store(self):
        for fmt, f in (("claude-stream", STREAM), ("claude-transcript", TRANSCRIPT),
                       ("codex-events", FIX / "codex_events.jsonl"), ("codex-session", FIX / "codex_session.jsonl")):
            self.assertIn(MARKER, Path(f).read_text(encoding="utf-8"), "the fixture does carry text")
            self.us("ingest", "--format", fmt, f)
        store = self.root / ".local" / "usage"
        self.assertEqual(sorted(p.name for p in store.iterdir()), ["agents.jsonl", "records.jsonl"])
        for p in store.iterdir():
            self.assertNotIn(MARKER, p.read_text(encoding="utf-8"))
        self.assertNotIn(MARKER, json.dumps(self.report()))

    def test_usage_store_and_fixtures_are_what_git_should_see(self):
        if not (REPO / ".git").exists() or not shutil.which("git"):
            self.skipTest("not a git checkout, or git is not installed")
        private = [".local/usage/records.jsonl", ".local/usage/agents.jsonl",
                   ".local/usage/model-checks.jsonl", ".local/usage/raw/x.claude.jsonl"]
        r = subprocess.run(["git", "check-ignore", *private], cwd=str(REPO), capture_output=True, text=True)
        self.assertEqual(sorted(r.stdout.split()), sorted(private), "every usage file must be ignored by git")
        tracked = subprocess.run(["git", "ls-files", ".local", "sessions"], cwd=str(REPO),
                                 capture_output=True, text=True).stdout.strip()
        self.assertEqual(tracked, "", "no usage log or session file is tracked")
        # the fixtures are the generator's output and nothing else: synthetic ids only
        for p in FIX.rglob("*.jsonl"):
            for line in p.read_text(encoding="utf-8").splitlines():
                for key in ("msg_", "resp_", "req_", "toolu_"):
                    for part in line.split('"'):
                        if part.startswith(key):
                            self.assertIn("SYN", part, f"{p.name}: {part} does not look synthetic")


if __name__ == "__main__":
    unittest.main()
