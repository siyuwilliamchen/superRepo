"""Gate for the requested-against-reported model check (tools/modelcheck.py).

What must hold:

- the model asked for, the model the host says it selected and the model the provider's
  response names are three separate fields, and the verdict is drawn only from the third;
- an alias that resolves, an exact id that matches, an id reported with a suffix, another model
  answering, and two models answering one run are told apart;
- whatever could not be read is listed as unknown with its reason, and is never filled in from
  the request: for Codex that is the provider-reported model itself;
- a choice the host does not advertise is refused before any worker starts, and a host that is
  not installed gives a record that says so.

The default tests start no worker and use no network: they read synthetic captures
(tools/tests/fixtures/usage/). Two live tests run one tiny worker on each installed host; they
are skipped unless LIVEOS_LIVE_MODELCHECK=1, because they spend a few provider tokens.

    python -m unittest tools/tests/test_modelcheck.py -v
    LIVEOS_LIVE_MODELCHECK=1 python -m unittest tools/tests/test_modelcheck.py -v
"""
from pathlib import Path
import json, os, shutil, subprocess, sys, tempfile, unittest

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools"
FIX = TOOLS / "tests" / "fixtures" / "usage"
LIVE = os.environ.get("LIVEOS_LIVE_MODELCHECK") == "1"


class ModelCheck(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="liveos-modelcheck-test-"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def mc(self, *args, ok=True, env_extra=None, timeout=120):
        env = dict(os.environ, LIVEOS_ROOT=str(self.root), **(env_extra or {}))
        r = subprocess.run([sys.executable, "-I", str(TOOLS / "modelcheck.py"), *map(str, args)], env=env,
                           capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        if ok:
            self.assertEqual(r.returncode, 0, f"modelcheck {args}\n{r.stdout}\n{r.stderr}")
        try:
            return r.returncode, json.loads(r.stdout)
        except Exception:
            return r.returncode, r.stdout + r.stderr

    def evaluate(self, host, model, capture, *extra):
        return self.mc("evaluate", "--host", host, "--model", model, "--capture", FIX / capture, *extra)[1]

    def unknown_fields(self, rec):
        return sorted(u["field"] for u in rec["unknown"])

    # ---- Claude: the provider's response names the model
    def test_exact_id_matches(self):
        r = self.evaluate("claude", "synth-claude-small-1", "claude_stream_small.jsonl", "--exit-code", "0")
        self.assertEqual(r["requested_kind"], "exact")
        self.assertEqual(r["host_resolved"], "synth-claude-small-1")
        self.assertEqual(r["provider_reported"], ["synth-claude-small-1"])
        self.assertEqual(r["host_accounted"], ["synth-claude-small-1"])
        self.assertEqual(r["verdict"], "match")
        self.assertEqual(r["unknown"], [])
        self.assertTrue(r["host_supported"])
        self.assertIn("message.model", r["provider_reported_source"])

    def test_alias_resolves_to_an_exact_id(self):
        r = self.evaluate("claude", "small", "claude_stream_small.jsonl", "--exit-code", "0")
        self.assertEqual((r["requested"], r["requested_kind"]), ("small", "alias"))
        self.assertEqual(r["verdict"], "alias_resolved")
        self.assertEqual(r["provider_reported"], ["synth-claude-small-1"], "the id, not the alias, is recorded")
        self.assertTrue(r["host_resolved_agrees_with_request"])

    def test_reported_id_with_a_suffix_is_its_own_verdict(self):
        r = self.evaluate("claude", "synth-claude-small-1", "claude_stream_dated.jsonl", "--exit-code", "0")
        self.assertEqual(r["verdict"], "match_with_suffix")
        self.assertEqual(r["provider_reported"], ["synth-claude-small-1-20260101"])

    def test_another_model_answering_is_a_mismatch(self):
        # the host says it selected the large model; the provider's response names the small one
        r = self.evaluate("claude", "synth-claude-large-1", "claude_stream_fallback.jsonl", "--exit-code", "0")
        self.assertEqual(r["host_resolved"], "synth-claude-large-1")
        self.assertTrue(r["host_resolved_agrees_with_request"])
        self.assertEqual(r["provider_reported"], ["synth-claude-small-1"])
        self.assertEqual(r["verdict"], "mismatch", "the host's word does not settle it; the response does")
        alias = self.evaluate("claude", "large", "claude_stream_fallback.jsonl", "--exit-code", "0")
        self.assertEqual(alias["verdict"], "mismatch")

    def test_two_models_in_one_run_is_mixed(self):
        r = self.evaluate("claude", "synth-claude-large-1", "claude_stream_mixed.jsonl", "--exit-code", "0")
        self.assertEqual(r["verdict"], "mixed")
        self.assertEqual(r["provider_reported"], ["synth-claude-large-1", "synth-claude-small-1"])
        self.assertEqual(r["responses"], 2)

    def test_a_run_with_no_response_is_unknown_not_a_match(self):
        r = self.evaluate("claude", "synth-claude-small-1", "claude_stream_error.jsonl", "--exit-code", "1")
        self.assertEqual(r["verdict"], "unknown")
        self.assertEqual(r["provider_reported"], [])
        self.assertEqual(r["host_resolved"], "synth-claude-small-1", "the host's selection is still recorded")
        self.assertIn("provider_reported", self.unknown_fields(r))
        self.assertIn("error_during_execution", next(u["why"] for u in r["unknown"]
                                                     if u["field"] == "provider_reported"))
        self.assertIsNone(r["host_supported"], "an errored run does not show the choice is supported")

    # ---- Codex: nothing read is the provider's own word, and the record says so
    def test_codex_reported_model_is_unknown_and_said_so(self):
        r = self.evaluate("codex", "synth-gpt-small-1", "codex_events.jsonl", "--exit-code", "0")
        self.assertEqual(r["verdict"], "unknown")
        self.assertEqual(r["provider_reported"], [])
        self.assertIsNone(r["host_resolved"])
        self.assertEqual(self.unknown_fields(r),
                         ["host_accounted", "host_resolved", "host_supported", "provider_reported"])
        self.assertEqual(r["run_id"], "syn-thread-0001")
        # with the saved session the client-applied model is known; the provider's still is not
        r = self.evaluate("codex", "synth-gpt-small-1", "codex_events.jsonl", "--exit-code", "0",
                          "--session-file", FIX / "codex_session.jsonl")
        self.assertEqual(r["host_resolved"], "synth-gpt-small-1")
        self.assertIn("applied by the client", r["host_resolved_source"])
        self.assertTrue(r["host_resolved_agrees_with_request"])
        self.assertEqual(r["verdict"], "unknown", "the client's setting is not the provider's statement")
        self.assertEqual(self.unknown_fields(r), ["host_accounted", "provider_reported"])
        for u in r["unknown"]:
            self.assertGreater(len(u["why"]), 20, "every unknown carries its reason")

    # ---- the choices a host advertises
    def test_unadvertised_choice_is_refused_before_any_worker_starts(self):
        home = self.root / "codex-home"
        home.mkdir()
        shutil.copy(FIX / "codex_models_cache.json", home / "models_cache.json")
        env = {"CODEX_HOME": str(home)}
        c = self.mc("choices", "--host", "codex", env_extra=env)[1]
        self.assertEqual(c["choices"], ["synth-gpt-small-1", "synth-gpt-large-1"])
        code, out = self.mc("run", "--host", "codex", "--model", "synth-gpt-unlisted", ok=False, env_extra=env)
        self.assertNotEqual(code, 0)
        self.assertIn("not among the choices", out)
        self.assertFalse((self.root / ".local" / "usage" / "model-checks.jsonl").exists(), "nothing ran")
        # Claude advertises no list; the tool says that instead of inventing one
        c = self.mc("choices", "--host", "claude")[1]
        self.assertIsNone(c["choices"])
        self.assertIn("no model list", c["basis"])

    def test_missing_host_is_recorded_as_unknown(self):
        empty = self.root / "empty-path"
        empty.mkdir()
        home = self.root / "codex-home"
        home.mkdir()
        shutil.copy(FIX / "codex_models_cache.json", home / "models_cache.json")
        env = {"PATH": str(empty), "CODEX_HOME": str(home)}
        for host, model in (("claude", "small"), ("codex", "synth-gpt-small-1")):
            code, r = self.mc("run", "--host", host, "--model", model, ok=False, env_extra=env)
            self.assertEqual(code, 3, r)
            self.assertEqual(r["verdict"], "unknown")
            self.assertIn("not on PATH", r["unknown"][0]["why"])
        rows = self.mc("list", "--json")[1]
        self.assertEqual([(x["host"], x["requested"], x["verdict"]) for x in rows],
                         [("claude-code", "small", "unknown"), ("codex", "synth-gpt-small-1", "unknown")])
        self.assertIn("unknown everything", self.mc("list")[1])

    def test_evaluate_records_only_when_asked(self):
        self.evaluate("claude", "small", "claude_stream_small.jsonl")
        self.assertEqual(self.mc("list", "--json")[1], [])
        self.evaluate("claude", "small", "claude_stream_small.jsonl", "--record")
        rows = self.mc("list", "--json")[1]
        self.assertEqual([(x["requested"], x["verdict"]) for x in rows], [("small", "alias_resolved")])
        self.assertIn("alias_resolved", self.mc("list")[1])

    # ---- live: one tiny worker per installed host
    @unittest.skipUnless(LIVE, "live model check skipped: set LIVEOS_LIVE_MODELCHECK=1 (spends a few provider tokens)")
    def test_live_claude_worker(self):
        if not shutil.which("claude"):
            self.skipTest("the claude command is not installed")
        model = os.environ.get("LIVEOS_LIVE_CLAUDE_MODEL", "haiku")
        code, r = self.mc("run", "--host", "claude", "--model", model, ok=False, timeout=400)
        self.assertEqual(code, 0, r)
        self.assertIn(r["verdict"], ("alias_resolved", "match", "match_with_suffix"))
        self.assertEqual(len(r["provider_reported"]), 1)
        self.assertEqual(r["unknown"], [])
        self.assertIn("--tools", r["worker"]["argv"])
        rep = json.loads(subprocess.run([sys.executable, "-I", str(TOOLS / "usage.py"), "report", "--json"],
                                        env=dict(os.environ, LIVEOS_ROOT=str(self.root)), capture_output=True,
                                        text=True, encoding="utf-8").stdout)
        p = rep["processes"][0]
        self.assertEqual((p["role"], p["stage"], p["outcome"]), ("probe", "modelcheck", "completed"))
        self.assertTrue(all(p["tokens"][c] is not None for c in ("input", "output", "cache_read", "cache_write")))
        self.assertEqual(rep["runs"][0]["verdict"], "reconciled")

    @unittest.skipUnless(LIVE, "live model check skipped: set LIVEOS_LIVE_MODELCHECK=1 (spends a few provider tokens)")
    def test_live_codex_worker(self):
        if not shutil.which("codex"):
            self.skipTest("the codex command is not installed")
        choices = self.mc("choices", "--host", "codex")[1]["choices"]
        if not choices:
            self.skipTest("this Codex installation advertises no model choices")
        model = os.environ.get("LIVEOS_LIVE_CODEX_MODEL", choices[0])
        code, r = self.mc("run", "--host", "codex", "--model", model, ok=False, timeout=400)
        self.assertEqual(code, 3, r)
        self.assertEqual(r["verdict"], "unknown", "until a Codex capture carries the provider's model")
        self.assertIn("provider_reported", [u["field"] for u in r["unknown"]])
        self.assertTrue(r["host_supported"])
        self.assertEqual(r["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
