"""Phase 4 gate for publication (LiveOS research through conversation, section 8 phase 4 and
acceptance case 7).

- a brief with an authorising turn and a write ticket builds a package and an edition
  (HTML always; PDF when the vault's renderer, Python Playwright + installed Chrome, is present);
- the same inputs rebuilt in a clean directory are byte-identical (PDF after normalising its
  volatile metadata);
- deleting a data file makes verify (and build) name that file precisely;
- a brief without a write ticket, a brief without an authorising turn, and a ticket that is not
  the brief's write ticket produce no draft;
- a later result produces a revision proposal and leaves the edition and the sources unchanged.

The brief is made with the real tools/conversationalist.py and tools/coordinator.py commands
against a scratch root (LIVEOS_ROOT), each call a new process, so the handoff is end to end.

    python -m unittest tools/tests/test_publish.py -v
"""
from pathlib import Path
import hashlib, json, os, shutil, subprocess, sys, tempfile, unittest

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def tree(d):
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(Path(d).rglob("*")) if p.is_file()}


class Publication(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="liveos-pub-"))
        (self.root / "workflow").mkdir()
        shutil.copy(REPO / "workflow" / "roster.json", self.root / "workflow" / "roster.json")
        topic = self.root / "topics" / "t1"
        topic.mkdir(parents=True)
        (topic / "index.md").write_text("# test topic\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], capture_output=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    # ---- helpers: every call is a fresh process
    def run_tool(self, tool, *args, ok=True):
        env = dict(os.environ, LIVEOS_ROOT=str(self.root))
        r = subprocess.run([sys.executable, "-I", str(TOOLS / tool), *args], env=env,
                           capture_output=True, text=True, encoding="utf-8", timeout=300)
        if ok:
            self.assertEqual(r.returncode, 0, f"{tool} {args}\n{r.stdout}\n{r.stderr}")
        try:
            return r.returncode, json.loads(r.stdout)
        except Exception:
            return r.returncode, r.stdout + r.stderr

    def cv(self, *a, **k):
        return self.run_tool("conversationalist.py", *a, **k)

    def co(self, *a, **k):
        return self.run_tool("coordinator.py", *a, **k)

    def pub(self, *a, **k):
        return self.run_tool("publish.py", *a, **k)

    def say(self, sid, text, speaker="william"):
        return self.cv("turn", "--session", sid, "--speaker", speaker, "--text", text)[1]["turn"]

    def ask(self, sid, turn, slug, claims, question="Did an effective amendment change the investor-consent threshold?"):
        return self.cv("ask", "--session", sid, "--turn", turn, "--kind", "research", "--slug", slug,
                       "--question", question, "--done-when", "Return old and new thresholds with locators.",
                       "--claims", claims, "--after-success", "interpret")[1]["receipt"]

    def work_through(self, tid, summary, claims):
        """A research worker and then the interpreter finish the ticket, as other processes."""
        a = self.co("claim", "--worker", "research-agent", "--kind", "research")[1]
        self.assertEqual(a["claimed"], tid)
        self.co("complete", tid, "--attempt-id", a["attempt_id"], "--summary", summary,
                "--sources", "S:amend-2 s.4", "--claims", claims)
        child = self.co("show", tid)[1]["derived_state"]["children"][0]
        ia = self.co("claim", "--worker", "interpreter", "--kind", "interpret")[1]
        self.co("complete", child, "--attempt-id", ia["attempt_id"], "--summary",
                "the threshold in the diagram changes; approval against remedy still holds", "--claims", claims)
        return child

    def conversation_to_brief(self, sid="S-08"):
        """The spec's worked example, up to 'Good enough. Write it.' Returns (brief path, write ticket)."""
        self.cv("open", "--session", sid, "--topic", "t1", "--question",
                "Who can allow or prevent the company from borrowing?")
        u1 = self.say(sid, "Organise it around where the deal can be stopped. Remedies on a separate branch.")
        self.cv("outline", "--session", sid, "--turn", u1, "--disposition", "explicit",
                "--entry", "foreground C-07; place condition C-12 at the decision it changes",
                "--claims", "C-07,C-12", "--scope", "only above the consent threshold")
        self.cv("outline", "--session", sid, "--turn", u1, "--disposition", "confirmed",
                "--entry", "draw remedy C-19 as a separate branch", "--claims", "C-19")
        self.cv("coverage", "--session", sid, "--point", "C-21", "--state", "deferred", "--turn", u1,
                "--note", "lender-side credit analysis, set aside")
        u2 = self.say(sid, "Did the amendment change the threshold?")
        t_amend = self.ask(sid, u2, "amendment-check", "C-12")
        self.work_through(t_amend, "threshold changed from 5m to 8m", "C-12")
        self.cv("catchup", "--session", sid, "--voice", "none")
        u3 = self.say(sid, "And when did the consent clause take effect?")
        t_open = self.ask(sid, u3, "effective-date", "C-07", question="When did the consent clause take effect?")
        u4 = self.say(sid, "Good enough. Write it.")
        code, refused = self.cv("brief", "--session", sid, "--turn", u4, ok=False)
        self.assertEqual(code, 2, "the open ticket on a lead claim blocks the brief until William accepts it")
        self.assertFalse((self.root / "sessions" / sid / "briefs").exists())
        out = self.cv("brief", "--session", sid, "--turn", u4, "--accept-limitation")[1]
        self.assertTrue(out["frozen"])
        self.assertEqual(out["limitations"][0]["ticket"], t_open)
        return out["brief"], out["write_ticket"], {"u4": u4, "t_open": t_open, "t_amend": t_amend}

    def edition(self, rid, ed="v1"):
        return self.root / "output" / "reports" / rid / ed

    # ---- the gate: one approval produces the package and the edition
    def test_approved_brief_builds_package_and_edition_and_rebuilds_byte_identical(self):
        self.assertFalse((self.root / "reports").exists(), "no draft exists before the brief")
        brief, ticket, ctx = self.conversation_to_brief()
        self.assertFalse((self.root / "reports").exists(), "freezing the brief does not draft anything")

        out = self.pub("scaffold", "--brief", brief, "--ticket", ticket)[1]
        rid = out["report_id"]
        pkg = self.root / "reports" / rid
        self.assertEqual(out["claims_in_order"], ["C-07", "C-12", "C-19"])
        for name in ("brief.json", "ticket.json", "publication.md", "manifest.json",
                     "data/claims.csv", "data/limitations.csv", "data/revisions.csv", "figures/claim-map.json"):
            self.assertTrue((pkg / name).is_file(), name)
        self.assertEqual(sha(pkg / "brief.json"), sha(self.root / brief), "the brief is copied byte for byte")
        self.assertTrue(list((pkg / "evidence").glob("T-*.json")), "the incorporated result's ledger record is kept")

        # the manifest: every input with sha256, the renderer and version, fonts, locale, timezone
        m = json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))
        inputs = {p.relative_to(pkg).as_posix() for p in pkg.rglob("*") if p.is_file()} - {"manifest.json"}
        self.assertEqual(set(m["inputs"]), inputs)
        for r, rec in m["inputs"].items():
            self.assertEqual(rec["sha256"], sha(pkg / r), r)
        self.assertEqual(m["renderer"]["name"], "tools/publish.py")
        self.assertTrue(m["renderer"]["version"])
        self.assertTrue(m["fonts"]["declared_stack"])
        self.assertEqual(m["locale"], "en-US")
        self.assertEqual(m["timezone"], "UTC")
        self.assertEqual(m["write_ticket"]["id"], ticket)
        self.assertEqual(m["brief"]["authorized_by_turn"], ctx["u4"])

        # publication.md: stable section ids, the claims in William's order, qualifications, omissions, limitations
        md = (pkg / "publication.md").read_text(encoding="utf-8")
        for sid in ("{#sec-question}", "{#sec-claims}", "{#sec-O-1}", "{#sec-O-2}", "{#sec-claim-register}",
                    "{#sec-qualifications}", "{#sec-omissions}", "{#sec-limitations}", "{#sec-revisions}"):
            self.assertIn(sid, md)
        self.assertLess(md.index("{#claim-C-07}"), md.index("{#claim-C-12}"))
        self.assertLess(md.index("{#claim-C-12}"), md.index("{#claim-C-19}"))
        self.assertIn("only above the consent threshold", md)
        self.assertIn("C-21", (pkg / "data" / "omissions.csv").read_text(encoding="utf-8"))
        self.assertIn(ctx["t_open"], (pkg / "data" / "limitations.csv").read_text(encoding="utf-8"))
        self.assertIn(ctx["t_amend"], (pkg / "data" / "revisions.csv").read_text(encoding="utf-8"))

        # build: html outside git, pdf if the renderer is there
        b = self.pub("build", "--report", rid)[1]
        ed = self.edition(rid)
        self.assertTrue((ed / "index.html").is_file())
        self.assertTrue((ed / "report.css").is_file())
        self.assertTrue((ed / "build.json").is_file())
        self.assertEqual(b["checks"]["broken_anchors"], [])
        self.assertEqual(b["checks"]["missing_files"], [])
        html = (ed / "index.html").read_text(encoding="utf-8")
        for anchor in ('id="sec-question"', 'id="sec-O-1"', 'id="claim-C-07"', 'id="claim-C-12"', 'id="claim-C-19"',
                       'id="sec-limitations"', '<svg'):
            self.assertIn(anchor, html)
        self.assertIn(ticket, html)
        self.assertNotIn("<!--", html, "writer notes do not reach the edition")
        if b["pdf"]["produced"]:
            self.assertTrue((ed / "index.pdf").is_file())
            self.assertGreater((ed / "index.pdf").stat().st_size, 1000)
            self.assertIn("Chromium", b["pdf"]["engine"])
            self.assertEqual(b["pdf"]["page_errors"], [])
            self.assertFalse(b["pdf"]["desktop_overflow"])
        else:
            self.assertTrue(b["pdf"]["missing"], "when no PDF is made the build says exactly what is missing")
        eds = json.loads((pkg / "editions.json").read_text(encoding="utf-8"))
        self.assertEqual([e["edition"] for e in eds], ["v1"])
        self.assertEqual(eds[0]["html_sha256"], sha(ed / "index.html"))

        # the same inputs, rebuilt in a clean directory, are byte-identical
        clean = self.root / "elsewhere" / "clean-build"
        self.pub("build", "--report", rid, "--out", str(clean))
        self.assertEqual((clean / "index.html").read_bytes(), (ed / "index.html").read_bytes())
        self.assertEqual((clean / "report.css").read_bytes(), (ed / "report.css").read_bytes())
        self.assertEqual((clean / "build.json").read_bytes(), (ed / "build.json").read_bytes())
        if b["pdf"]["produced"]:
            self.assertEqual(json.loads((clean / "build.json").read_text(encoding="utf-8"))["pdf"]["normalised_sha256"],
                             b["pdf"]["normalised_sha256"])
        v = self.pub("verify", "--report", rid)[1]
        self.assertTrue(v["verified"], v)
        self.assertTrue(all(r["same"] for r in v["files"]), v["files"])
        if b["pdf"]["produced"]:
            self.assertIn("index.pdf", [r["file"] for r in v["files"]])

    # ---- acceptance case 7: a missing immutable input is named precisely
    def test_missing_data_file_is_named_by_verify_and_build(self):
        brief, ticket, _ = self.conversation_to_brief()
        rid = self.pub("scaffold", "--brief", brief, "--ticket", ticket)[1]["report_id"]
        self.pub("build", "--report", rid, "--no-pdf")
        pkg = self.root / "reports" / rid
        target = pkg / "data" / "claims.csv"
        saved = target.read_bytes()
        target.unlink()
        code, out = self.pub("verify", "--report", rid, ok=False)
        self.assertEqual(code, 3)
        self.assertEqual([m["path"] for m in out["missing_inputs"]], [f"reports/{rid}/data/claims.csv"])
        self.assertIn(f"reports/{rid}/data/claims.csv", out["reason"])
        self.assertIn(hashlib.sha256(saved).hexdigest(), out["reason"])
        code, out = self.pub("build", "--report", rid, "--no-pdf", ok=False)
        self.assertEqual(code, 3)
        self.assertEqual([m["path"] for m in out["missing_inputs"]], [f"reports/{rid}/data/claims.csv"])
        # a changed input is told apart from a missing one
        target.write_bytes(saved + b"x,y,z\n")
        code, out = self.pub("verify", "--report", rid, ok=False)
        self.assertEqual(code, 4)
        self.assertEqual([m["path"] for m in out["changed_inputs"]], [f"reports/{rid}/data/claims.csv"])
        # restored byte for byte, the edition verifies again
        target.write_bytes(saved)
        self.assertTrue(self.pub("verify", "--report", rid)[1]["verified"])

    # ---- zero drafts before approval
    def test_brief_without_write_ticket_or_authorising_turn_produces_no_draft(self):
        # a roster with no writer: the Coordinator refuses the write ticket, the brief is frozen without one
        roster = json.loads((self.root / "workflow" / "roster.json").read_text(encoding="utf-8"))
        roster["roles"]["report-writer"]["capabilities"] = []
        (self.root / "workflow" / "roster.json").write_text(json.dumps(roster), encoding="utf-8")
        sid = "S-09"
        self.cv("open", "--session", sid, "--topic", "t1", "--question", "Q?")
        u1 = self.say(sid, "Foreground C-07.")
        self.cv("outline", "--session", sid, "--turn", u1, "--disposition", "explicit", "--entry", "foreground C-07", "--claims", "C-07")
        u2 = self.say(sid, "Good enough. Write it.")
        out = self.cv("brief", "--session", sid, "--turn", u2)[1]
        self.assertTrue(out["frozen"])
        self.assertIsNone(out["write_ticket"])
        brief = out["brief"]
        code, ref = self.pub("scaffold", "--brief", brief, "--ticket", "T-0001", ok=False)
        self.assertNotEqual(code, 0)
        self.assertIn("not in the ledger", ref["reason"])
        self.assertFalse((self.root / "reports").exists(), "no draft without the write ticket")

        # a ticket exists, but it is a research ticket, not the brief's write ticket
        t_res = self.ask(sid, u2, "probe", "C-07")
        code, ref = self.pub("scaffold", "--brief", brief, "--ticket", t_res, ok=False)
        self.assertNotEqual(code, 0)
        self.assertIn("not the brief's write ticket", ref["reason"])
        self.assertFalse((self.root / "reports").exists())

        # the writer is back; a real write ticket; but a brief whose authorising turn was removed is refused
        roster["roles"]["report-writer"]["capabilities"] = ["write"]
        (self.root / "workflow" / "roster.json").write_text(json.dumps(roster), encoding="utf-8")
        self.cv("flush", "--session", sid)
        tickets = [json.loads(l) for l in (self.root / "sessions" / sid / "tickets.jsonl").read_text(encoding="utf-8").splitlines()]
        write_ticket = next(t["receipt"] for t in tickets if t["kind"] == "write" and t.get("receipt"))
        bpath = self.root / brief
        b = json.loads(bpath.read_text(encoding="utf-8"))
        b["authorized_by_turn"] = None
        unauth = bpath.with_name("brief-unauthorised.json")
        unauth.write_text(json.dumps(b), encoding="utf-8")
        code, ref = self.pub("scaffold", "--brief", str(unauth), "--ticket", write_ticket, ok=False)
        self.assertNotEqual(code, 0)
        self.assertIn("no authorising turn", ref["reason"])
        self.assertFalse((self.root / "reports").exists())
        # and the genuine brief with its own write ticket goes through
        out = self.pub("scaffold", "--brief", brief, "--ticket", write_ticket)[1]
        self.assertTrue((self.root / "reports" / out["report_id"] / "manifest.json").is_file())

    # ---- a later result: proposal, edition unchanged
    def test_later_result_makes_a_revision_proposal_and_leaves_the_edition_unchanged(self):
        brief, ticket, ctx = self.conversation_to_brief()
        rid = self.pub("scaffold", "--brief", brief, "--ticket", ticket)[1]["report_id"]
        self.pub("build", "--report", rid, "--no-pdf")
        pkg = self.root / "reports" / rid
        ed = self.edition(rid)
        edition_before = tree(ed)
        sources_before = {k: v for k, v in tree(pkg).items() if k != "editions.json"}

        # the open ticket on C-07 lands after publication
        interp = self.work_through(ctx["t_open"], "the clause took effect on signing; the threshold applies from day one", "C-07")
        out = self.pub("revise", "--report", rid, "--result", interp)[1]
        self.assertTrue(out["material"])
        self.assertEqual(out["affected_claims"], ["C-07"])
        self.assertIn("sec-O-1", out["affected_sections"])
        self.assertIn("claim-C-07", out["affected_sections"])
        prop = json.loads((pkg / "revisions" / "proposal-1.json").read_text(encoding="utf-8"))
        self.assertEqual(prop["published_edition"]["edition"], "v1")
        self.assertEqual(prop["published_edition"]["html_sha256"], sha(ed / "index.html"))
        self.assertEqual(prop["later_result"]["ticket"], interp)
        self.assertEqual(prop["later_result"]["answers"], ctx["t_open"])
        self.assertEqual(prop["closes_limitation"], [ctx["t_open"]])
        self.assertTrue((pkg / "revisions" / "proposal-1.md").is_file())

        # nothing published or frozen has moved
        self.assertEqual(tree(ed), edition_before)
        self.assertEqual({k: v for k, v in tree(pkg).items() if k != "editions.json" and not k.startswith("revisions/")},
                         sources_before)
        self.assertTrue(self.pub("verify", "--report", rid)[1]["verified"])

        # the same result given as an inbox item makes a second proposal, still without touching the edition
        box = [json.loads(l) for l in (self.root / "sessions" / "S-08" / "inbox.jsonl").read_text(encoding="utf-8").splitlines()]
        n = next(i for i, it in enumerate(box, 1) if it["ticket"] == interp)
        out2 = self.pub("revise", "--report", rid, "--result", f"sessions/S-08/inbox.jsonl:{n}")[1]
        self.assertEqual(out2["proposal"], f"reports/{rid}/revisions/proposal-2.json")
        self.assertEqual(tree(ed), edition_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
