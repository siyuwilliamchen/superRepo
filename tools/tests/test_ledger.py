"""Acceptance tests for the artifact ledger and Housekeeper pilot (handoff section 7).

Seven exercises, one test each, on a generated two-domain fixture: domain `alpha` owns a
dataset and research drafts, domain `beta` owns a figure built from alpha's CSV, the report
that shows it, and pages that merely link. Every step runs tools/ledger.py as a new process
against the fixture (LIVEOS_ROOT), so each call is also a restart. The fixture carries its own
copy of tools/vault_trim.py and its own backup folder, so retire goes through the real
zip-verify-delete without touching the vault. The last test is the read-only baseline: it
inventories the real IPO-timing chain and prints its dependency chain, changing nothing.

    python -m unittest tools/tests/test_ledger.py -v
"""
from pathlib import Path
import hashlib, json, os, shutil, subprocess, sys, tempfile, unittest

REPO = Path(__file__).resolve().parents[2]
LEDGER = REPO / "tools" / "ledger.py"

SERIES_V1 = "year,value\n2020,1\n2021,2\n2022,3\n"
SERIES_V2 = "year,value\n2020,1\n2021,2\n2022,3\n2023,5\n"
BUILD_PY = '''"""Deterministic build: series.csv -> fig.svg + report.html (no timestamps)."""
import csv, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
rows = list(csv.DictReader(open(ROOT / "alpha" / "research" / "D-1" / "data" / "series.csv", encoding="utf-8")))
pts = " ".join(f"{i*20},{100-int(r['value'])*10}" for i, r in enumerate(rows))
svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><polyline points="{pts}" fill="none" stroke="black"/></svg>\\n'
html = "<html><body><h1>Report</h1><p>values: " + ",".join(r["value"] for r in rows) + '</p><img src="fig.svg"></body></html>\\n'
here = Path(__file__).resolve().parent
for name, body in (("fig.svg", svg), ("report.html", html)):
    tmp = here / (".tmp-" + name)
    tmp.write_text(body, encoding="utf-8"); os.replace(tmp, here / name)
'''


def sha(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ledger-test-")).resolve()
        (self.root / "workflow").mkdir()
        shutil.copy(REPO / "workflow" / "roster.json", self.root / "workflow" / "roster.json")
        (self.root / "tools").mkdir()
        shutil.copy(REPO / "tools" / "vault_trim.py", self.root / "tools" / "vault_trim.py")
        (self.root / ".local").mkdir()
        (self.root / "backup" / "originals").mkdir(parents=True)
        (self.root / ".local" / "library-locations.json").write_text(
            json.dumps({"local-originals-2026-11-08": str(self.root / "backup" / "originals")}), encoding="utf-8")
        (self.root / "catalog" / "sources").mkdir(parents=True)
        (self.root / "catalog" / "sources" / "library.jsonl").write_text("", encoding="utf-8")
        # domain alpha: dataset, drafts, previews.  domain beta: build code, figure, report, pages
        self.w("alpha/research/D-1/data/series.csv", SERIES_V1)
        self.w("alpha/research/D-1/draft-v1.md", "# draft v1\nsuperseded notes on consent thresholds\n")
        self.w("alpha/research/D-1/notes.md", "# notes\nfirst version\n")
        self.w("alpha/research/D-1/preview-a.png", "PNGa")
        self.w("alpha/research/D-1/preview-b.png", "PNGb")
        self.w("beta/pages/rep/build.py", BUILD_PY)
        self.w("beta/pages/other.html", '<a href="../../alpha/research/D-1/draft-v1.md">draft</a>\n')
        self.w("beta/pages/legacy.html", "<p>legacy page quoting values 1,2,3 with no manifest</p>\n")
        self.build()
        for d in ("alpha", "beta"):
            (self.root / "ledger" / d).mkdir(parents=True)
            (self.root / "ledger" / d / "domain.json").write_text(json.dumps({"domain": d, "roots": [d]}), encoding="utf-8")
        (self.root / ".local" / "stage").mkdir()
        self.git("init", "-q"); self.git("add", "-A"); self.git("commit", "-q", "-m", "fixture")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    # ---- helpers
    def w(self, relpath, text):
        p = self.root / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))           # exact bytes: no newline translation on Windows
        return relpath

    def staged(self, name, text):
        p = self.root / ".local" / "stage" / name
        p.write_bytes(text.encode("utf-8"))
        return str(p)

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       check=True, capture_output=True)

    def build(self):
        subprocess.run([sys.executable, "-I", str(self.root / "beta" / "pages" / "rep" / "build.py")], check=True)

    def led(self, *args, ok=True, env=None):
        e = dict(os.environ, LIVEOS_ROOT=str(self.root), **(env or {}))
        r = subprocess.run([sys.executable, "-I", str(LEDGER), *args], env=e, capture_output=True,
                           text=True, encoding="utf-8", timeout=120)
        if ok:
            self.assertEqual(r.returncode, 0, f"{args}\n{r.stdout}\n{r.stderr}")
        try:
            return r.returncode, json.loads(r.stdout)
        except Exception:
            return r.returncode, r.stdout + r.stderr

    def batch(self, key, ops, ticket="T-1", role="research-agent", ok=True, env=None):
        f = self.root / ".local" / f"batch-{key}.json"
        f.write_text(json.dumps({"op_key": key, "ticket": ticket, "attempt_id": f"{ticket}#a1", "role": role, "ops": ops}),
                     encoding="utf-8")
        return self.led("batch", "--file", str(f), ok=ok, env=env)

    def create(self, key, domain, path, source=None, role="research-agent", **kw):
        op = dict(op="create", domain=domain, path=path, source=source, **kw)
        code, r = self.batch(key, [op], role=role)
        return r["results"][0]["id"]

    def show(self, aid):
        return self.led("show", "--id", aid)[1]

    def records(self):
        out = {}
        for p in (self.root / "ledger").glob("*/artifacts-*.jsonl"):
            for line in p.read_text(encoding="utf-8").splitlines():
                r = json.loads(line); out[r["id"]] = r
        return out

    def fixture_files(self):
        return [p for p in self.root.rglob("*") if p.is_file() and ".git" not in p.parts and ".local" not in p.parts]

    # ---- exercise 1
    def test_1_create_twice_modify_and_rename_across_domains(self):
        ops = [{"op": "create", "domain": "alpha", "path": "alpha/research/D-1/data/series.csv", "kind": "dataset",
                "purpose": "yearly values behind the consent report", "topics": ["consent"]},
               {"op": "create", "domain": "alpha", "path": "alpha/research/D-1/notes.md", "kind": "findings",
                "purpose": "working notes", "topics": ["consent"]}]
        code, first = self.batch("K1", ops)
        self.assertEqual([x["version"] for x in first["results"]], [1, 1])
        a, b = (x["id"] for x in first["results"])
        before = self.records()
        code, again = self.batch("K1", ops)                     # the acknowledgment was lost; retry
        self.assertEqual(again["already"], "accepted")
        self.assertEqual(again["results"], first["results"])
        self.assertEqual(self.records(), before, "one effect per operation key")
        self.assertEqual(len(list((self.root / "ledger" / "receipts").glob("*.json"))), 1)

        # modify one: new bytes, new version, same identity
        src = self.staged("notes2.md", "# notes\nsecond version\n")
        code, r = self.batch("K2", [{"op": "modify", "id": b, "expected_version": 1, "source": src}])
        self.assertEqual(r["results"][0]["version"], 2)
        self.assertEqual((self.root / "alpha/research/D-1/notes.md").read_text(encoding="utf-8"), "# notes\nsecond version\n")
        code, out = self.batch("K2-stale", [{"op": "modify", "id": b, "expected_version": 1, "source": src}], ok=False)
        self.assertIn("is at v2, writer expected v1", out)

        # rename across domains: id kept, both domain views updated by the one operation
        code, r = self.batch("K3", [{"op": "move", "id": b, "expected_version": 2, "to": "beta/pages/notes.md", "domain": "beta"}],
                             role="report-writer")
        self.assertEqual(r["results"][0]["version"], 3)
        shown = self.show(b)
        self.assertEqual((shown["domain"], shown["path"], shown["version"]), ("beta", "beta/pages/notes.md", 3))
        self.assertEqual(shown["digest"], sha(self.root / "beta/pages/notes.md"))
        self.assertTrue((self.root / "beta/pages/notes.md").is_file())
        self.assertFalse((self.root / "alpha/research/D-1/notes.md").exists())
        alpha_ids = {json.loads(l)["id"] for p in (self.root / "ledger/alpha").glob("artifacts-*.jsonl")
                     for l in p.read_text(encoding="utf-8").splitlines()}
        beta_ids = {json.loads(l)["id"] for p in (self.root / "ledger/beta").glob("artifacts-*.jsonl")
                    for l in p.read_text(encoding="utf-8").splitlines()}
        self.assertEqual((a in alpha_ids, b in alpha_ids, b in beta_ids), (True, False, True))
        self.assertEqual({i["id"] for i in self.led("find", "--domain", "beta")[1]["items"]}, {b})
        topic = self.led("find", "--topic", "consent")[1]
        self.assertEqual({i["id"]: i["path"] for i in topic["items"]},
                         {a: "alpha/research/D-1/data/series.csv", b: "beta/pages/notes.md"})
        self.assertIn("ledger:generated", (self.root / "ledger/beta/index.md").read_text(encoding="utf-8"))

    # ---- exercise 2
    def test_2_cross_domain_dependency_chain_vs_navigation_link(self):
        csv_id = self.create("c1", "alpha", "alpha/research/D-1/data/series.csv", kind="dataset", purpose="yearly values", topics=["consent"])
        draft = self.create("c2", "alpha", "alpha/research/D-1/draft-v1.md", kind="findings", purpose="superseded draft", topics=["consent"])
        code_id = self.create("c3", "beta", "beta/pages/rep/build.py", role="report-writer", kind="build-code",
                              purpose="builds fig and report from series.csv", inputs=[{"id": csv_id}])
        fig = self.create("c4", "beta", "beta/pages/rep/fig.svg", role="report-writer", kind="figure",
                          purpose="figure 1 of the consent report", inputs=[{"id": csv_id, "digest": "pin"}, {"id": code_id}])
        rep = self.create("c5", "beta", "beta/pages/rep/report.html", role="report-writer", kind="report-source",
                          purpose="published consent report", policy="approved-edition", topics=["consent"],
                          inputs=[{"id": fig}, {"id": code_id}])
        other = self.create("c6", "beta", "beta/pages/other.html", role="report-writer", kind="report-source",
                            purpose="unrelated page that links to the draft", links=[draft])

        rb = self.led("required-by", "--id", csv_id)[1]
        chain = {(e["id"], e["requires"]) for e in rb["required_by"]}
        self.assertIn((fig, csv_id), chain)                        # direct, across domains
        self.assertIn((rep, fig), chain)                           # through the intermediate figure
        self.assertEqual({e["domain"] for e in rb["required_by"]}, {"beta"})
        self.assertEqual(rb["measures"]["file_bodies_opened"], 0)
        self.assertEqual(rb["measures"]["model_calls"], 0)
        pinned = [i for i in self.show(fig)["inputs"] if i["id"] == csv_id][0]
        self.assertEqual(pinned["digest"], sha(self.root / "alpha/research/D-1/data/series.csv"))

        plan = self.led("housekeep", "plan", "--domain", "alpha", "--request", "remove superseded drafts on consent")[1]
        by = {i["id"]: i for i in plan["items"]}
        self.assertEqual(by[csv_id]["disposition"], "held")
        self.assertTrue(any(fig in r and "beta" in r for r in by[csv_id]["reasons"]), by[csv_id]["reasons"])
        self.assertTrue(any(rep in r and f"via {fig}" in r for r in by[csv_id]["reasons"]), by[csv_id]["reasons"])
        self.assertEqual(by[draft]["disposition"], "eligible")
        self.assertTrue(any("navigation link from " + other in r for r in by[draft]["reasons"]), by[draft]["reasons"])
        self.assertEqual(plan["measures"]["file_bodies_opened"], 2, "one targeted digest check per candidate")
        self.assertEqual(plan["measures"]["model_calls"], 0)
        print("\n  Housekeeper result with a cross-domain hold:", json.dumps(by[csv_id], indent=1))

    # ---- exercise 3
    def test_3_legacy_consumer_without_manifest_and_external_edit(self):
        empty = self.led("housekeep", "plan", "--domain", "alpha", "--request", "clean alpha")[1]
        self.assertEqual(empty["index_size"], 0)
        self.assertIn("empty index", empty["warning"])
        self.assertEqual(empty["items"], [])
        code, out = self.led("housekeep", "approve", "--plan", empty["plan"], "--ids", "A-nothing", "--by", "william", ok=False)
        self.assertNotEqual(code, 0)

        csv_id = self.create("c1", "alpha", "alpha/research/D-1/data/series.csv", kind="dataset", purpose="yearly values",
                             coverage="unverified")       # beta's legacy pages have never been reconciled
        legacy = self.led("register", "--op-key", "r1", "--ticket", "T-9", "--domain", "beta", "--path", "beta/pages/legacy.html",
                          "--kind", "report-source")[1]["results"][0]["id"]
        self.assertEqual(self.show(legacy)["state"], "inventoried")
        plan = self.led("housekeep", "plan", "--domain", "alpha", "--request", "clean alpha datasets")[1]
        item = [i for i in plan["items"] if i["id"] == csv_id][0]
        self.assertEqual(item["disposition"], "unresolved")
        self.assertTrue(any("not reconciled" in r for r in item["reasons"]))
        cost = plan["reconciliation_cost"]["unregistered_files_under_domain_roots"]["alpha"]
        self.assertGreater(cost["files"], 0); self.assertGreater(cost["bytes"], 0)
        code, out = self.led("housekeep", "approve", "--plan", plan["plan"], "--ids", csv_id, "--by", "william", ok=False)
        self.assertIn("unresolved", out)

        # a human edits the registered file outside the write path
        with open(self.root / "alpha/research/D-1/data/series.csv", "a", encoding="utf-8") as f:
            f.write("2023,4\n")
        drift = self.led("drift", "--domain", "alpha")[1]
        self.assertEqual([d["id"] for d in drift["drift"]], [csv_id])
        self.assertIn("differ from record (external edit)", drift["drift"][0]["drift"])
        self.assertEqual(drift["drift"][0]["git"], "M")
        src = self.staged("s.csv", SERIES_V2)
        code, out = self.batch("m1", [{"op": "modify", "id": csv_id, "expected_version": 1, "source": src}], ok=False)
        self.assertIn("drift", out)
        rec = self.led("register", "--op-key", "rc1", "--ticket", "T-9", "--domain", "alpha", "--path",
                       "alpha/research/D-1/data/series.csv", "--reconcile")[1]
        self.assertEqual(rec["results"][0]["op"], "reconcile"); self.assertEqual(rec["results"][0]["version"], 2)
        self.assertEqual(self.show(csv_id)["changed"]["provenance"], "external edit accepted by reconcile")
        after = self.led("drift", "--domain", "alpha")[1]
        self.assertEqual(after["drift"], [], "record and disk agree again")
        self.assertEqual([(u["id"], u["git"]) for u in after["uncommitted"]], [(csv_id, "M")], "git still lacks the bytes")

    # ---- exercise 4
    def test_4_pin_after_plan_and_replacement_at_a_reused_path(self):
        x = self.create("c1", "alpha", "alpha/research/D-1/tmp.csv", source=self.staged("t.csv", "a,b\n1,2\n"), kind="dataset", purpose="scratch")
        y = self.create("c2", "alpha", "alpha/research/D-1/old.csv", source=self.staged("o.csv", "old\n"), kind="dataset", purpose="old table")
        plan = self.led("housekeep", "plan", "--domain", "alpha", "--request", "remove scratch datasets")[1]
        self.assertEqual({i["id"]: i["disposition"] for i in plan["items"]}, {x: "eligible", y: "eligible"})
        self.led("housekeep", "approve", "--plan", plan["plan"], "--ids", f"{x},{y}", "--by", "william")

        self.led("hold", "--id", x, "--job", "J-7", "--ticket", "T-3")           # a job pins x after the plan
        self.batch("w1", [{"op": "retire", "id": y, "expected_version": 1, "reason": "replaced by new table"}])
        z = self.create("w2", "alpha", "alpha/research/D-1/old.csv", source=self.staged("n.csv", "new\n"), kind="dataset", purpose="new table")
        self.assertNotEqual(z, y)

        applied = self.led("housekeep", "apply", "--plan", plan["plan"], "--op-key", "HK1", "--ticket", "T-4")[1]
        self.assertEqual(applied["outcome"]["retired"], [])
        self.assertEqual(applied["outcome"]["held"][0]["id"], x)
        self.assertIn("job hold: J-7", applied["outcome"]["held"][0]["reasons"][0])
        self.assertEqual(applied["outcome"]["changed"][0]["id"], y)
        self.assertEqual(applied["outcome"]["changed"][0]["now"]["state"], "retired")
        self.assertEqual((self.root / "alpha/research/D-1/old.csv").read_text(encoding="utf-8"), "new\n")
        self.assertEqual(self.show(z)["state"], "active")

        # replaying the old receipt, or the stale writer, affects neither the pinned input nor the replacement
        self.assertEqual(self.led("housekeep", "apply", "--plan", plan["plan"], "--op-key", "HK1", "--ticket", "T-4")[1]["already"], "accepted")
        code, out = self.batch("stale", [{"op": "modify", "id": y, "expected_version": 1, "source": self.staged("s.csv", "stale\n")}], ok=False)
        self.assertIn("is retired", out)
        code, out = self.batch("stale2", [{"op": "create", "domain": "alpha", "path": "alpha/research/D-1/old.csv",
                                           "source": self.staged("s2.csv", "stale\n"), "purpose": "x"}], ok=False)
        self.assertIn(f"already artifact {z}", out)
        self.assertEqual((self.root / "alpha/research/D-1/old.csv").read_text(encoding="utf-8"), "new\n")
        self.assertEqual(self.show(x)["state"], "active")

        self.led("release", "--job", "J-7")
        plan2 = self.led("housekeep", "plan", "--domain", "alpha", "--request", "remove scratch datasets", "--kind", "dataset")[1]
        self.assertEqual([i["disposition"] for i in plan2["items"] if i["id"] == x], ["eligible"])
        self.led("housekeep", "approve", "--plan", plan2["plan"], "--ids", x, "--by", "william")
        done = self.led("housekeep", "apply", "--plan", plan2["plan"], "--op-key", "HK2", "--ticket", "T-4")[1]
        self.assertEqual([r["id"] for r in done["outcome"]["retired"]], [x])
        self.assertFalse((self.root / "alpha/research/D-1/tmp.csv").exists())
        tomb = self.show(x)
        self.assertEqual(tomb["state"], "retired")
        self.assertEqual(tomb["retired"]["reason"], "remove scratch datasets")
        self.assertTrue(Path(tomb["retired"]["restore"]["zip"]).is_file())
        self.assertEqual(done["savings"]["removed_paths"], 1)
        print("\n  Example receipt (housekeep apply):", json.dumps({k: done[k] for k in ("receipt", "ticket", "plan", "results", "savings")}, indent=1))

    # ---- exercise 5
    def test_5_interruptions_converge_and_restore_works(self):
        a = self.create("c1", "alpha", "alpha/research/D-1/notes.md", kind="findings", purpose="notes")
        v1 = sha(self.root / "alpha/research/D-1/notes.md")

        # interrupted between staging and acceptance
        src2 = self.staged("n2.md", "second\n")
        code, out = self.batch("K2", [{"op": "modify", "id": a, "expected_version": 1, "source": src2}], ok=False,
                               env={"LIVEOS_LEDGER_CRASH": "after-stage"})
        self.assertEqual(code, 3)
        self.assertTrue((self.root / ".local/ledger/pending/K2.json").is_file())
        self.assertEqual(self.records()[a]["version"], 1)
        rec = self.led("recover")[1]
        self.assertEqual(rec["actions"][0]["action"], "staged only; discarded (retry the batch)")
        self.assertEqual(sha(self.root / "alpha/research/D-1/notes.md"), v1)
        code, r = self.batch("K2", [{"op": "modify", "id": a, "expected_version": 1, "source": src2}])
        self.assertEqual(r["results"][0]["version"], 2)

        # interrupted after acceptance, before the views were refreshed
        src3 = self.staged("n3.md", "third\n")
        code, out = self.batch("K3", [{"op": "modify", "id": a, "expected_version": 2, "source": src3}], ok=False,
                               env={"LIVEOS_LEDGER_CRASH": "after-accept"})
        self.assertEqual(code, 3)
        self.assertTrue((self.root / "ledger/receipts/K3.json").is_file())
        self.assertFalse(self.led("index", "--check")[1]["current"])
        rec = self.led("recover")[1]
        self.assertIn("accepted before the interruption", rec["actions"][0]["action"])
        self.assertTrue(rec["index"]["current"])
        shown = self.show(a)
        self.assertEqual((shown["version"], shown["digest"]), (3, sha(self.root / "alpha/research/D-1/notes.md")))
        self.assertEqual((self.root / "alpha/research/D-1/notes.md").read_text(encoding="utf-8"), "third\n")
        self.assertEqual(self.batch("K3", [{"op": "modify", "id": a, "expected_version": 2, "source": src3}])[1]["already"], "accepted")

        # retire, then restore; a consumer registered afterwards sees the restored id
        self.batch("K4", [{"op": "retire", "id": a, "expected_version": 3, "reason": "test retire"}])
        self.assertFalse((self.root / "alpha/research/D-1/notes.md").exists())
        code, out = self.batch("K4b", [{"op": "modify", "id": a, "expected_version": 4, "source": src3}], ok=False)
        self.assertIn("is retired", out)
        self.batch("K5", [{"op": "restore", "id": a}])
        shown = self.show(a)
        self.assertEqual((shown["state"], shown["version"], shown["path"]), ("active", 5, "alpha/research/D-1/notes.md"))
        self.assertEqual(shown["digest"], sha(self.root / "alpha/research/D-1/notes.md"))
        self.assertEqual((self.root / "alpha/research/D-1/notes.md").read_text(encoding="utf-8"), "third\n")
        b = self.create("K6", "beta", "beta/pages/uses-notes.html", source=self.staged("u.html", "<p>uses notes</p>"),
                        role="report-writer", kind="report-source", purpose="page built from the notes", inputs=[{"id": a}])
        self.assertEqual([e["id"] for e in self.led("required-by", "--id", a)[1]["required_by"]], [b])
        keys = sorted(p.stem for p in (self.root / "ledger/receipts").glob("*.json"))
        self.assertEqual(keys, ["K2", "K3", "K4", "K5", "K6", "c1"])
        d = self.led("drift")[1]
        self.assertEqual(d["drift"], [], "current paths and digests agree with the records")
        self.assertEqual({u["id"] for u in d["uncommitted"]}, {a, b}, "accepted but not yet committed is reported apart")

        # id/path conflicts on restore
        self.batch("K7", [{"op": "retire", "id": a, "expected_version": 5, "reason": "again", "force": True}])
        c = self.create("K8", "alpha", "alpha/research/D-1/notes.md", source=self.staged("c.md", "other\n"), kind="findings", purpose="new notes")
        code, out = self.batch("K9", [{"op": "restore", "id": a}], ok=False)
        self.assertIn(f"path conflict, alpha/research/D-1/notes.md is now {c}", out)
        self.batch("K9", [{"op": "restore", "id": a, "to": "alpha/research/D-1/notes-restored.md"}])
        self.assertEqual((self.root / "alpha/research/D-1/notes-restored.md").read_text(encoding="utf-8"), "third\n")
        self.assertEqual((self.root / "alpha/research/D-1/notes.md").read_text(encoding="utf-8"), "other\n")
        print("\n  Example operation + receipt (K5 restore):", json.dumps(json.loads((self.root / "ledger/receipts/K5.json").read_text(encoding="utf-8")), indent=1))

    # ---- exercise 6
    def test_6_hard_link_sibling_keeps_bytes_and_report_rebuilds(self):
        main = self.root / "alpha/research/D-1/data/series.csv"
        twin = self.root / "alpha/research/D-1/data/series-twin.csv"
        os.link(main, twin)
        self.assertEqual(main.stat().st_nlink, 2)
        s = self.create("c1", "alpha", "alpha/research/D-1/data/series.csv", kind="dataset", purpose="series")
        t = self.create("c2", "alpha", "alpha/research/D-1/data/series-twin.csv", kind="dataset", purpose="twin")
        plan = self.led("housekeep", "plan", "--domain", "alpha", "--request", "x")[1]
        self.assertTrue(any("shares storage" in r for i in plan["items"] if i["id"] == s for r in i["reasons"]))

        # edit one path: the new bytes go to a new file; the sibling keeps its bytes
        self.batch("m1", [{"op": "modify", "id": s, "expected_version": 1, "source": self.staged("v2.csv", SERIES_V2)}])
        self.assertEqual(main.read_bytes(), SERIES_V2.encode())
        self.assertEqual(twin.read_bytes(), SERIES_V1.encode())
        self.assertEqual((main.stat().st_nlink, twin.stat().st_nlink), (1, 1))
        self.assertEqual(self.show(t)["digest"], sha(twin), "the twin's record still matches its bytes")

        # retire the edited one: the recovery copy holds the edited bytes, the sibling is untouched
        r = self.batch("r1", [{"op": "retire", "id": s, "expected_version": 2, "reason": "pilot"}])[1]["results"][0]
        self.assertEqual(r["backup"]["digest"], "sha256:" + hashlib.sha256(SERIES_V2.encode()).hexdigest())
        self.assertEqual(r["physical_bytes_freed"], len(SERIES_V2.encode()))
        self.assertTrue(r["backup"]["verified"])
        self.assertEqual(twin.read_bytes(), SERIES_V1.encode())
        self.batch("r2", [{"op": "restore", "id": s}])
        self.assertEqual(main.read_bytes(), SERIES_V2.encode())

        # rebuild an approved report from retained sources after an unrelated draft is retired
        code_id = self.create("c3", "beta", "beta/pages/rep/build.py", role="report-writer", kind="build-code", purpose="build", inputs=[{"id": s}])
        self.build()
        fig = self.create("c4", "beta", "beta/pages/rep/fig.svg", role="report-writer", kind="figure", purpose="fig", inputs=[{"id": s, "digest": "pin"}, {"id": code_id}])
        rep = self.create("c5", "beta", "beta/pages/rep/report.html", role="report-writer", kind="report-source", purpose="report",
                          policy="approved-edition", inputs=[{"id": fig}, {"id": code_id}])
        draft = self.create("c6", "alpha", "alpha/research/D-1/draft-v1.md", kind="findings", purpose="superseded draft")
        plan = self.led("housekeep", "plan", "--domain", "alpha", "--kind", "findings", "--request", "remove superseded drafts")[1]
        self.led("housekeep", "approve", "--plan", plan["plan"], "--ids", draft, "--by", "william")
        done = self.led("housekeep", "apply", "--plan", plan["plan"], "--op-key", "HK", "--ticket", "T-5")[1]
        self.assertEqual([x["id"] for x in done["outcome"]["retired"]], [draft])
        self.assertEqual(done["savings"]["physical_bytes_freed_measured"], done["savings"]["logical_bytes"], "measured: nlink was 1")
        before = {p: sha(self.root / p) for p in ("beta/pages/rep/fig.svg", "beta/pages/rep/report.html")}
        self.build()
        self.assertEqual({p: sha(self.root / p) for p in before}, before, "data and figures regenerate identically")
        self.assertEqual(self.show(fig)["digest"], before["beta/pages/rep/fig.svg"])
        self.assertEqual(self.led("drift")[1]["drift"], [], "the rebuild reproduced the registered bytes")

    # ---- exercise 7
    def test_7_find_by_subject_then_clean_expired_previews(self):
        s = self.create("c1", "alpha", "alpha/research/D-1/data/series.csv", kind="dataset", purpose="consent thresholds, yearly", topics=["consent"])
        r = self.create("c2", "beta", "beta/pages/rep/report.html", role="report-writer", kind="report-source",
                        purpose="report on investor consent thresholds", topics=["consent"], inputs=[{"id": s}])
        pa = self.create("c3", "alpha", "alpha/research/D-1/preview-a.png", kind="derivative", purpose="preview render",
                         topics=["consent"], policy="disposable", expires="2026-01-01")
        pb = self.create("c4", "alpha", "alpha/research/D-1/preview-b.png", kind="derivative", purpose="preview render",
                         topics=["consent"], policy="disposable", expires="2099-01-01")
        self.create("c5", "alpha", "alpha/research/D-1/notes.md", kind="findings", purpose="other subject", topics=["other"])

        found = self.led("find", "--topic", "consent")[1]
        self.assertEqual({i["id"] for i in found["items"]}, {s, r, pa, pb})
        self.assertEqual({i["domain"] for i in found["items"]}, {"alpha", "beta"})
        self.assertEqual(found["measures"]["file_bodies_opened"], 0, "a fully registered case uses metadata only")
        self.assertEqual(found["measures"]["model_calls"], 0)
        self.assertLessEqual(found["measures"]["index_queries"], 6)
        text = self.led("find", "--text", "consent thresholds")[1]
        self.assertEqual({i["id"] for i in text["items"]}, {s, r})

        plan = self.led("housekeep", "plan", "--topic", "consent", "--kind", "derivative", "--expired", "--request", "remove expired consent previews")[1]
        self.assertEqual({i["id"]: i["disposition"] for i in plan["items"]}, {pa: "eligible"})
        self.assertEqual(plan["measures"]["file_bodies_opened"], 1, "targeted verification of the one candidate")
        self.assertLess(plan["measures"]["file_bodies_opened"], len(self.fixture_files()), "no whole-vault content scan")
        self.led("housekeep", "approve", "--plan", plan["plan"], "--ids", pa, "--by", "william")
        done = self.led("housekeep", "apply", "--plan", plan["plan"], "--op-key", "HK7", "--ticket", "T-7")[1]
        self.assertEqual([x["id"] for x in done["outcome"]["retired"]], [pa])
        self.assertTrue((self.root / "alpha/research/D-1/preview-b.png").is_file())
        self.assertEqual(done["measures"]["model_calls"], 0)
        print("\n  Measures, steady state: find =", found["measures"], "| plan =", plan["measures"], "| apply =", done["measures"])

    # ---- protections
    def test_protected_roots_and_role_scope_are_refused(self):
        self.w("alpha/inputs/William_x.md", "supplied\n")
        code, out = self.batch("p1", [{"op": "create", "domain": "alpha", "path": "alpha/inputs/William_x.md", "purpose": "x"}], ok=False)
        self.assertIn("protected root", out)
        code, out = self.batch("p2", [{"op": "create", "domain": "beta", "path": "beta/pages/other.html", "purpose": "x"}],
                               role="research-agent", ok=False)
        self.assertIn("outside the write scope of role research-agent", out)
        code, out = self.batch("p3", [{"op": "register", "domain": "x", "path": ".git/HEAD"}], ok=False)
        self.assertIn("protected root", out)
        self.assertEqual(self.records(), {})
        self.assertEqual(list((self.root / ".local/ledger/pending").glob("*.json")), [], "a refused batch leaves no intent behind")


class BaselineReadOnly(unittest.TestCase):
    """The real IPO-timing chain, inventoried without writing anything."""
    ROOTS = ["Economics/pages/ipo-timing", "Economics/graphs/ipo_age", "Economics/research/IPOAGE-DATA"]

    def snapshot(self):
        out = {}
        for root in self.ROOTS:
            for p in sorted((REPO / root).rglob("*")):
                if p.is_file():
                    st = p.stat(); out[str(p)] = (st.st_size, st.st_mtime_ns)
        return out

    def test_baseline_inventory_prints_the_chain_and_changes_nothing(self):
        if not all((REPO / r).is_dir() for r in self.ROOTS):
            self.skipTest("IPO-timing chain not present")
        before = self.snapshot()
        status_before = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", *self.ROOTS],
                                       capture_output=True, text=True).stdout
        index_before = (REPO / ".local/ledger/index.sqlite3").stat().st_mtime_ns if (REPO / ".local/ledger/index.sqlite3").exists() else None
        target = "Economics/pages/ipo-timing/stay-private-law.html"
        r = subprocess.run([sys.executable, "-I", str(LEDGER), "inventory", "--domain", "economics", "--roots", *self.ROOTS,
                            "--infer-inputs", "--chain", target], env=dict(os.environ, LIVEOS_ROOT=str(REPO)),
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        inv = json.loads(r.stdout)
        self.assertFalse(inv["written"])
        self.assertEqual(inv["files"], 30, "15 under graphs/ipo_age, 6 pages, 8 CSVs, findings.md")
        req = {(e["consumer"].split("/")[-1], e["requires"].split("/")[-1]) for e in inv["chain"]["requires"]}
        self.assertIn(("stay-private-law.html", "build_page.py"), req)
        self.assertIn(("build_page.py", "page_charts.py"), req)
        self.assertIn(("page_charts.py", "ritter_tables_by_year.csv"), req)
        self.assertIn(("page_charts.py", "computed_age_by_year.csv"), req)
        self.assertTrue(any("holders_at_ipo.csv" in x for g in inv["gaps"] for x in g["names_inputs_not_in_roots"]))
        print("\n  IPO-timing chain (read-only baseline), what", target, "requires:")
        for e in sorted(inv["chain"]["requires"], key=lambda e: (e["consumer"], e["requires"])):
            print(f"    {e['consumer']}  <-  {e['requires']}  [{e['kind']}]")
        print("  gaps:", json.dumps(inv["gaps"]))
        print("  bootstrap measures:", inv["measures"])
        self.assertEqual(self.snapshot(), before, "nothing under the roots changed")
        status_after = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", *self.ROOTS],
                                      capture_output=True, text=True).stdout
        self.assertEqual(status_after, status_before)
        index_after = (REPO / ".local/ledger/index.sqlite3").stat().st_mtime_ns if (REPO / ".local/ledger/index.sqlite3").exists() else None
        self.assertEqual(index_after, index_before, "a dry-run inventory touches no index")


if __name__ == "__main__":
    unittest.main(verbosity=2)
