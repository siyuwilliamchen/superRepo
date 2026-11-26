"""Tests for tools/claimmap.py, the Interpreter's claim-map tool (LiveOS design, section 3
"Interpreter" and the result contract in section 4; phase 3).

What is checked:
  - the real first map of the seed topic validates and keeps the ids tickets already use
    (C-07, C-12, C-19), every important claim says what William would misunderstand, and
    every claim's evidence level is one of the vault's tags;
  - the validator refuses the shapes the design forbids (an unknown relation, an edge to a
    claim that does not exist, an important claim without its omission consequence, a
    settled rival with no winner, a gap with no scope checked, a level-U claim with evidence
    missing its scope);
  - the diff of two revisions is the compact difference the result contract wants: only the
    claims that changed, by id, with the old and new conclusion, new edges, rivals opened or
    settled, gaps opened, and the ids list a completion passes as --claims;
  - the CLI runs as a separate process and returns non-zero on a bad map.

    python -m unittest tools/tests/test_claimmap.py -v
"""
from pathlib import Path
import copy, json, os, subprocess, sys, tempfile, unittest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "claimmap.py"
sys.path.insert(0, str(REPO / "tools"))
import claimmap  # noqa: E402
import vaults    # noqa: E402

# The seed topic's real map is domain content and lives in a vault, which is an explicit external
# input (config/vaults.json). When no registered vault holds it, the RealMap tests skip; the
# fixture-based tests below run everywhere.
TOPIC = vaults.resolve("topics/borrowing-consent")
REAL_MAP = claimmap.latest_map(TOPIC) if TOPIC else None
NO_REAL_MAP = "no vault with topics/borrowing-consent/claims/ is registered on this machine"


def minimal_map(**over):
    m = {
        "schema_version": 1, "topic": "t1", "revision": 1, "previous_revision": None,
        "domain": "corporate-law", "profile": "topics/t1/profile.md",
        "governing_question": "Who may do X?", "method": "profile", "source_revisions": {"git": "x"},
        "written": "2026-11-26", "by": {"worker": "w"},
        "claims": [
            {"id": "C-07", "title": "board", "conclusion": "The board decides.", "level": "R",
             "important": True, "status": "supported",
             "evidence": [{"ref": "a.md", "locator": "line 1", "tag": "R"}],
             "inference": "statute", "scope": "Delaware", "changes_if": "charter says otherwise",
             "missed_if_skipped": "he would think the investor authorises"},
            {"id": "C-12", "title": "threshold", "conclusion": "Only above $X.", "level": "S",
             "important": False, "status": "supported",
             "evidence": [{"ref": "b.md", "locator": "line 2", "tag": "S"}],
             "inference": "clause", "scope": "model", "changes_if": "amendment"},
        ],
        "edges": [{"from": "C-12", "relation": "qualifies", "to": "C-07"}],
        "rivals": [], "gaps": [], "requests": [],
    }
    m.update(over)
    return m


class RealMap(unittest.TestCase):
    def setUp(self):
        if REAL_MAP is None:
            self.skipTest(NO_REAL_MAP)
        self.path = REAL_MAP
        self.m = claimmap.load(self.path)

    def test_validates(self):
        self.assertEqual(claimmap.validate(self.m), [])

    def test_keeps_ticket_ids_and_omission_consequences(self):
        ids = {c["id"] for c in self.m["claims"]}
        for must in ("C-07", "C-12", "C-19"):
            self.assertIn(must, ids)
        for c in self.m["claims"]:
            self.assertIn(c["level"], claimmap.LEVELS, c["id"])
            if c["important"]:
                self.assertTrue(c["missed_if_skipped"].strip(), c["id"])
            for e in c["evidence"]:
                self.assertTrue(e["ref"] and e["locator"], c["id"])
        relations = {e["relation"] for e in self.m["edges"]}
        self.assertTrue(relations <= set(claimmap.RELATIONS))
        self.assertTrue(any(r["status"] == "open" for r in self.m["rivals"]),
                        "the void-against-remedy question is open in the vault; the map must say so")

    def test_evidence_refs_resolve(self):
        """A vault citation resolves to a file that exists (the design, section 3)."""
        for c in self.m["claims"]:
            for e in c["evidence"]:
                self.assertIsNotNone(vaults.resolve(e["ref"]), f"{c['id']}: {e['ref']} missing in every registered root")

    def test_print_one_claim(self):
        text = claimmap.render(self.m, "C-19")
        self.assertIn("C-19", text)
        self.assertIn("if missed", text)
        self.assertIn("Rival", text)

    def test_revision_chain(self):
        """Every revision after the first names the one before it and diffs against it."""
        maps = sorted(TOPIC.glob("claims/map-r*.json"))
        if len(maps) < 2:
            self.skipTest("one revision only")
        by_rev = {claimmap.load(p)["revision"]: claimmap.load(p) for p in maps}
        for r, m in by_rev.items():
            if m["previous_revision"] is not None:
                self.assertIn(m["previous_revision"], by_rev, f"r{r} names a missing previous revision")
                d = claimmap.diff(by_rev[m["previous_revision"]], m)
                self.assertTrue(d["claim_ids_changed"], f"r{r} changes nothing against r{m['previous_revision']}")


class Validator(unittest.TestCase):
    def test_minimal_ok(self):
        self.assertEqual(claimmap.validate(minimal_map()), [])

    def test_unknown_relation(self):
        m = minimal_map()
        m["edges"][0]["relation"] = "supports"
        self.assertTrue(any("relation" in e for e in claimmap.validate(m)))

    def test_edge_to_missing_claim(self):
        m = minimal_map()
        m["edges"].append({"from": "C-07", "relation": "requires", "to": "C-99"})
        self.assertTrue(any("C-99" in e for e in claimmap.validate(m)))

    def test_important_without_omission_consequence(self):
        m = minimal_map()
        del m["claims"][0]["missed_if_skipped"]
        self.assertTrue(any("missed_if_skipped" in e for e in claimmap.validate(m)))

    def test_bad_level_and_duplicate_id(self):
        m = minimal_map()
        m["claims"][1]["level"] = "X"
        m["claims"][1]["id"] = "C-07"
        errs = claimmap.validate(m)
        self.assertTrue(any("level" in e for e in errs))
        self.assertTrue(any("duplicate" in e for e in errs))

    def test_level_u_needs_scope_and_not_found_status(self):
        m = minimal_map()
        m["claims"][1].update({"level": "U", "status": "supported", "evidence": []})
        errs = claimmap.validate(m)
        self.assertTrue(any("level-U" in e for e in errs))
        m["claims"][1].update({"status": "not-found", "scope": ""})
        self.assertTrue(any("'scope'" in e for e in claimmap.validate(m)))

    def test_claim_above_u_needs_evidence(self):
        m = minimal_map()
        m["claims"][1]["evidence"] = []
        self.assertTrue(any("evidence reference" in e for e in claimmap.validate(m)))

    def test_rival_rules(self):
        m = minimal_map()
        m["rivals"] = [{"id": "RV-01", "about": ["C-07"], "readings": [{"name": "a", "conclusion": "x", "assumption": "y", "evidence": []}],
                        "differing_assumption": "d", "distinguishing_observation": "o", "status": "settled"}]
        errs = claimmap.validate(m)
        self.assertTrue(any("two readings" in e for e in errs))
        self.assertTrue(any("settled_for" in e for e in errs))

    def test_gap_needs_scope_checked(self):
        m = minimal_map()
        m["gaps"] = [{"id": "U-01", "what": "x", "scope_checked": "", "load_bearing": True, "claims": ["C-07"]}]
        self.assertTrue(any("scope_checked" in e for e in claimmap.validate(m)))

    def test_previous_revision_below_revision(self):
        m = minimal_map(revision=2, previous_revision=2)
        self.assertTrue(any("previous_revision" in e for e in claimmap.validate(m)))


class Diff(unittest.TestCase):
    def setUp(self):
        self.old = minimal_map()
        self.new = copy.deepcopy(self.old)
        self.new["revision"], self.new["previous_revision"] = 2, 1
        self.new["claims"][1]["conclusion"] = "Only above $Y, and only while preferred is outstanding."
        self.new["claims"].append({"id": "C-19", "title": "remedy", "conclusion": "A claim, not invalidity.",
                                   "level": "I", "important": True, "status": "open",
                                   "evidence": [{"ref": "c.md", "locator": "line 3", "tag": "I"}],
                                   "inference": "contract", "scope": "IRA", "changes_if": "void words",
                                   "missed_if_skipped": "he would think the loan is void"})
        self.new["edges"].append({"from": "C-12", "relation": "changes the consequence of", "to": "C-19"})
        self.new["rivals"] = [{"id": "RV-01", "about": ["C-19"],
                               "readings": [{"name": "void", "conclusion": "v", "assumption": "a", "evidence": []},
                                            {"name": "remedy", "conclusion": "r", "assumption": "b", "evidence": []}],
                               "differing_assumption": "where the consent sits",
                               "distinguishing_observation": "read the executed charter", "status": "open"}]
        self.new["gaps"] = [{"id": "U-01", "what": "no borrowing case", "scope_checked": "LAW-DOC cards",
                             "load_bearing": True, "claims": ["C-19"]}]
        self.new["requests"] = [{"kind": "research", "question": "What does the executed charter say?",
                                 "done_when": "wording with locator", "claims": ["C-19"]}]

    def test_compact_difference(self):
        d = claimmap.diff(self.old, self.new)
        self.assertEqual(d["claim_ids_changed"], ["C-12", "C-19"])
        self.assertEqual([c["id"] for c in d["claims"]["added"]], ["C-19"])
        self.assertEqual([c["id"] for c in d["claims"]["changed"]], ["C-12"])
        self.assertEqual(d["claims"]["unchanged"], ["C-07"])
        self.assertIn("conclusion", d["claims"]["changed"][0]["fields"])
        self.assertEqual(len(d["edges"]["added"]), 1)
        self.assertEqual([r["id"] for r in d["rivals"]["opened"]], ["RV-01"])
        self.assertEqual([g["id"] for g in d["gaps"]["opened"]], ["U-01"])
        self.assertEqual(len(d["requests_new"]), 1)
        text = claimmap.render_diff(d)
        self.assertIn("r1 → r2", text)
        self.assertIn("~ C-12", text)
        self.assertIn("+ C-19", text)
        self.assertIn("rival RV-01 opened", text)
        self.assertNotIn("C-07 [", text, "an unchanged claim is not restated")

    def test_no_change(self):
        d = claimmap.diff(self.old, copy.deepcopy(self.old))
        self.assertEqual(d["claim_ids_changed"], [])
        self.assertIn("No change of conclusion", claimmap.render_diff(d))

    def test_settled_rival_shows(self):
        n2 = copy.deepcopy(self.new)
        n2["rivals"][0].update({"status": "settled", "settled_for": "remedy"})
        d = claimmap.diff(self.new, n2)
        self.assertEqual([r["id"] for r in d["rivals"]["settled"]], ["RV-01"])
        self.assertIn("settled for: remedy", claimmap.render_diff(d))

    def test_widened_rival_shows(self):
        """A rival that gains a third reading is a change of conclusion, not silence."""
        n2 = copy.deepcopy(self.new)
        n2["rivals"][0]["readings"].append({"name": "voidable", "conclusion": "stands until set aside",
                                            "assumption": "Moelis line", "evidence": []})
        d = claimmap.diff(self.new, n2)
        self.assertEqual([r["id"] for r in d["rivals"]["changed"]], ["RV-01"])
        text = claimmap.render_diff(d)
        self.assertIn("~ rival RV-01", text)
        self.assertIn("void | remedy | voidable", text)
        self.assertEqual(d["claim_ids_changed"], [], "a rival change alone does not change a claim id")


class Cli(unittest.TestCase):
    def run_tool(self, *args):
        return subprocess.run([sys.executable, "-I", str(TOOL), *args], capture_output=True,
                              text=True, encoding="utf-8", timeout=60)

    def test_validate_ok_and_bad(self):
        with tempfile.TemporaryDirectory() as td:
            good, bad = Path(td) / "good.json", Path(td) / "bad.json"
            good.write_text(json.dumps(minimal_map()), encoding="utf-8")
            m = minimal_map()
            m["edges"][0]["relation"] = "nope"
            bad.write_text(json.dumps(m), encoding="utf-8")
            r = self.run_tool("validate", str(good))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("ok", r.stdout)
            r = self.run_tool("validate", str(bad))
            self.assertEqual(r.returncode, 1)
            self.assertIn("relation", r.stdout)

    def test_diff_and_ids_cli(self):
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td) / "r1.json", Path(td) / "r2.json"
            old = minimal_map()
            new = copy.deepcopy(old)
            new["revision"], new["previous_revision"] = 2, 1
            new["claims"][0]["conclusion"] = "The board decides, by majority."
            a.write_text(json.dumps(old), encoding="utf-8")
            b.write_text(json.dumps(new), encoding="utf-8")
            r = self.run_tool("diff", str(a), str(b))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("~ C-07", r.stdout)
            r = self.run_tool("diff", str(a), str(b), "--json")
            self.assertEqual(json.loads(r.stdout)["claim_ids_changed"], ["C-07"])
            r = self.run_tool("ids", str(b), "--changed-from", str(a))
            self.assertEqual(r.stdout.strip(), "C-07")
            r = self.run_tool("ids", str(b))
            self.assertEqual(r.stdout.strip(), "C-07,C-12")

    def test_latest_real_topic(self):
        if REAL_MAP is None:
            self.skipTest(NO_REAL_MAP)
        r = self.run_tool("latest", str(TOPIC))
        self.assertEqual(r.returncode, 0)
        self.assertIn("claims/map-r", r.stdout)


if __name__ == "__main__":
    unittest.main()
