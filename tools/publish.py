"""Publication: a frozen writing brief and its write ticket become a package of publication
sources under reports/<report-id>/, and that package builds deterministically into HTML (and
PDF where the vault's existing renderer is available) outside git.

Phase 4 of "LiveOS research through conversation" (William's design, 2026-11-25, sections 3
"Writer", 4 "Good enough, write it", 6 and 8). What was built and where it departs from the
design is in system/methods/publication.md.

  scaffold   brief + write ticket -> reports/<report-id>/ (brief copy, publication.md with
             stable section and claim ids, data/*.csv, figures/*.json, evidence/, manifest.json).
             Refused unless the brief names its authorising turn and the ticket is the brief's
             own write ticket in the ledger: work before approval produces no draft.
  freeze     after the Writer edits the sources: recompute manifest.json (the brief and ticket
             copies must still match the originals)
  build      manifest -> output/reports/<report-id>/<edition>/ (index.html, report.css, index.pdf
             when Chrome + Playwright are present, build.json). Refuses when an input is missing
             or changed, naming it.
  verify     rebuild into a second directory and compare bytes with the published edition;
             a missing immutable input is named precisely
  revise     a later result (ticket id or inbox item) -> reports/<id>/revisions/proposal-N
             linked to the published edition, which is not changed
  status     packages, editions, proposals

No clock and no network are used in the generation path. The rendered files depend only on
the package bytes, this script and the pinned renderer settings; the PDF additionally depends
on the installed Chrome, whose version the build record names.
"""
from pathlib import Path
import argparse, csv, hashlib, html, io, json, os, platform, re, shutil, sys

sys.path.insert(0, str(Path(__file__).resolve().parent))   # python -I drops the script dir
import coordinator as co                                     # noqa: E402

ROOT, SESSIONS = co.ROOT, co.SESSIONS
REPORTS = ROOT / "reports"
OUTPUT = ROOT / "output" / "reports"
PUBLISH_VERSION = "1.0.0"          # renderer version; bump on any change to the HTML, CSS or SVG it emits
MANIFEST_SCHEMA = 1
CHROME_DEFAULT = "C:/Program Files/Google/Chrome/Application/chrome.exe"
NOT_INPUTS = ("manifest.json", "editions.json")            # package files that are not build inputs
NOT_INPUT_DIRS = ("revisions",)
FONT_STACK = ["Segoe UI", "Noto Sans", "Microsoft YaHei", "Arial", "sans-serif"]
PAGE = {"size": "A4", "margin": "18mm 16mm", "width_px": 1100}

THEME_CSS = """/* shared report theme: tools/publish.py """ + PUBLISH_VERSION + """ */
:root { --ink: #1b1b1b; --muted: #5a5a5a; --rule: #cfcfcf; --card: #f6f6f4; --tint: #eef3fb; --accent: #1d5fb8; --warn: #b25a12; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --ink: #ececec; --muted: #b5b5b5; --rule: #444; --card: #202124; --tint: #1c2733; --accent: #7fb0f0; --warn: #e0905a; } }
:root[data-theme="dark"] { --ink: #ececec; --muted: #b5b5b5; --rule: #444; --card: #202124; --tint: #1c2733; --accent: #7fb0f0; --warn: #e0905a; }
html { color: var(--ink); background: transparent; }
body { margin: 0 auto; max-width: 1000px; padding: 24px 20px 48px; font: 16px/1.5 """ + ", ".join('"%s"' % f if " " in f else f for f in FONT_STACK) + """; }
header.report { border-bottom: 2px solid var(--ink); padding-bottom: 10px; margin-bottom: 18px; }
header.report .kicker { color: var(--muted); font-size: 14px; }
h1 { font-size: 28px; line-height: 1.2; margin: 6px 0 8px; }
h2 { font-size: 21px; margin: 28px 0 8px; border-top: 1px solid var(--rule); padding-top: 14px; }
h3 { font-size: 17px; margin: 18px 0 6px; }
h2 .anchor, h3 .anchor { color: var(--muted); font-size: 12px; font-weight: 400; margin-left: 8px; text-decoration: none; }
nav.toc { font-size: 14px; background: var(--card); border: 1px solid var(--rule); border-radius: 6px; padding: 8px 14px; }
nav.toc ol { margin: 4px 0 0; padding-left: 1.4em; columns: 2 240px; }
.scroll { overflow-x: auto; max-width: 100%; }
table { border-collapse: collapse; width: 100%; font-size: 14px; margin: 8px 0 14px; }
th, td { border: 1px solid var(--rule); padding: 5px 8px; text-align: left; vertical-align: top; }
th { background: var(--card); }
tr { break-inside: avoid; }
figure { margin: 14px 0 18px; break-inside: avoid; }
figure svg { max-width: 100%; height: auto; display: block; }
figcaption { font-size: 14px; color: var(--muted); margin-top: 4px; }
.claim { font-family: Consolas, "Courier New", monospace; font-size: 0.92em; background: var(--tint); padding: 0 4px; border-radius: 3px; white-space: nowrap; }
.limitation { border-left: 4px solid var(--warn); padding: 6px 12px; background: var(--card); }
.placeholder { color: var(--muted); font-style: italic; }
blockquote { margin: 8px 0; padding: 4px 14px; border-left: 3px solid var(--accent); color: var(--muted); }
code { font-family: Consolas, "Courier New", monospace; font-size: 0.92em; }
footer.report { margin-top: 36px; border-top: 1px solid var(--rule); padding-top: 8px; font-size: 13px; color: var(--muted); }
@page { size: """ + PAGE["size"] + """; margin: """ + PAGE["margin"] + """; }
@media print { body { max-width: none; padding: 0; font-size: 12.5px; } h2 { break-after: avoid; } nav.toc ol { columns: 2; } a { color: inherit; } }
"""


# ---------------------------------------------------------------- small helpers
def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(p):
    return sha256_bytes(Path(p).read_bytes())


def write_text(path, text):
    """Deterministic text file: UTF-8, LF, written atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    tmp.replace(path)


def write_json(path, payload):
    write_text(path, json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rel(p):
    p = Path(p).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def refuse(msg, code=2):
    print(json.dumps({"refused": True, "reason": msg}, ensure_ascii=False, indent=1))
    raise SystemExit(code)


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def session_turn_exists(session, turn):
    m = re.fullmatch(r"u-(\d+)", turn or "")
    if not m:
        return False
    d = SESSIONS / session / "turns"
    if not d.is_dir():
        return False
    for p in sorted(d.glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("id") == turn:
                return True
    return False


def ticket_result(tid):
    """The ticket and its terminal result from the ledger (None if not finished)."""
    path = co.ticket_path(tid)
    if not path:
        return None, None
    ticket = read_json(path)
    st = co.state_of(tid)
    return ticket, (st["result"] if st["state"] in co.TERMINAL else None)


# ---------------------------------------------------------------- the package
class Package:
    def __init__(self, report_id):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}", report_id or ""):
            raise SystemExit("publish: a report id is letters, digits, . _ - only")
        self.id = report_id
        self.dir = REPORTS / report_id

    @property
    def manifest_path(self):
        return self.dir / "manifest.json"

    def manifest(self):
        if not self.manifest_path.is_file():
            raise SystemExit(f"publish: no package reports/{self.id}/ (no manifest.json); scaffold it first")
        return read_json(self.manifest_path)

    def editions(self):
        p = self.dir / "editions.json"
        return read_json(p) if p.is_file() else []

    def input_files(self):
        out = []
        for p in sorted(self.dir.rglob("*")):
            if not p.is_file():
                continue
            r = p.relative_to(self.dir).as_posix()
            if r in NOT_INPUTS or r.split("/")[0] in NOT_INPUT_DIRS or r.endswith(".tmp"):
                continue
            out.append(r)
        return out

    def check_inputs(self, manifest):
        """Every listed input present with its recorded sha256. Returns (missing, changed, extra)."""
        listed = manifest["inputs"]
        missing, changed = [], []
        for r in sorted(listed):
            p = self.dir / r
            if not p.is_file():
                missing.append(r)
            elif sha256_file(p) != listed[r]["sha256"]:
                changed.append(r)
        extra = [r for r in self.input_files() if r not in listed]
        return missing, changed, extra

    def refuse_unless_intact(self, manifest, verb):
        missing, changed, extra = self.check_inputs(manifest)
        if missing or changed or extra:
            detail = {"missing_inputs": [{"path": f"reports/{self.id}/{r}", **manifest["inputs"][r]} for r in missing],
                      "changed_inputs": [{"path": f"reports/{self.id}/{r}", "expected_sha256": manifest["inputs"][r]["sha256"],
                                          "actual_sha256": sha256_file(self.dir / r)} for r in changed],
                      "unlisted_files": [f"reports/{self.id}/{r}" for r in extra]}
            first = (f"immutable input missing: reports/{self.id}/{missing[0]} (sha256 {manifest['inputs'][missing[0]]['sha256']}, "
                     f"{manifest['inputs'][missing[0]]['bytes']} bytes, listed in reports/{self.id}/manifest.json)" if missing else
                     f"input changed since the manifest was frozen: reports/{self.id}/{changed[0]}; run freeze to refreeze" if changed else
                     f"file not in the manifest: reports/{self.id}/{extra[0]}; run freeze to include it")
            print(json.dumps({"refused": True, "command": verb, "reason": first, **detail}, ensure_ascii=False, indent=1))
            raise SystemExit(3 if missing else 4)

    def build_manifest(self, base):
        inputs = {}
        for r in self.input_files():
            p = self.dir / r
            inputs[r] = {"sha256": sha256_file(p), "bytes": p.stat().st_size}
        m = dict(base)
        m.update({"schema_version": MANIFEST_SCHEMA, "report_id": self.id, "inputs": inputs,
                  "renderer": {"name": "tools/publish.py", "version": PUBLISH_VERSION,
                               "markdown": "built-in subset (headings with {#id}, lists, pipe tables, images that "
                                           "point at data/*.csv or figures/*.json, links, bold, code)",
                               "figures": "declarative JSON -> inline SVG, grid layout, no seeds",
                               "theme_sha256": sha256_bytes(THEME_CSS.encode("utf-8")),
                               "pdf": {"engine": "Chromium via Python Playwright (the renderer tools/build_platform_pilot.py uses)",
                                       "page": PAGE, "print_background": True, "prefer_css_page_size": True,
                                       "volatile_metadata_normalised_for_comparison": ["/CreationDate", "/ModDate", "/ID"]}},
                  "fonts": {"declared_stack": FONT_STACK,
                            "note": "system fonts; no font file is shipped, so glyph shapes in the PDF follow the "
                                    "installed faces of the build machine, which build.json names by OS"},
                  "data_ordering": "every CSV is written in the brief's order and read in file order; no sorting at render time",
                  "layout_seeds": "none: figure layout is a deterministic grid",
                  "clock": "not used: every date shown is a recorded input"})
        return m


# ---------------------------------------------------------------- scaffold
def default_report_id(brief):
    return f"{brief['session']}-{brief['id']}"


def claims_in_order(brief):
    seen, out = set(), []
    for e in brief.get("ordered_claims") or []:
        for c in e.get("claims") or []:
            if c not in seen:
                seen.add(c)
                out.append(c)
    return out


def csv_text(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    return buf.getvalue()


def answers_of(evidence, tid):
    """The ticket William's request first created (an interpret ticket answers a research ticket)."""
    return ((evidence.get(tid) or {}).get("answers") or {}).get("id") or tid


def asked_of(evidence, tid):
    return ((evidence.get(tid) or {}).get("answers") or {}).get("question") or ""


def scaffold_sources(brief, ticket, evidence, locale):
    """The publication sources the Writer starts from. Everything comes from the brief."""
    q = (brief.get("governing_question") or {})
    order = claims_in_order(brief)
    entries = brief.get("ordered_claims") or []
    quals = brief.get("required_qualifications") or []
    omissions = brief.get("deliberate_omissions") or {}
    disagreements = brief.get("outstanding_disagreements") or {}
    limitations = brief.get("limitations") or []
    revisions = brief.get("evidence_and_interpretation_revisions") or []

    # data: small CSVs worth reading in a diff
    claim_rows = []
    for i, e in enumerate(entries, 1):
        for c in e.get("claims") or []:
            qual = next((x.get("scope") for x in quals if x.get("id") == e.get("outline")), "")
            claim_rows.append([i, e.get("outline"), e.get("turn"), e.get("disposition"), c, e.get("entry"), qual or ""])
    data = {
        "data/claims.csv": csv_text(["order", "outline", "turn", "disposition", "claim", "entry", "qualification"], claim_rows),
        "data/omissions.csv": csv_text(["point", "state", "turn", "note"],
                                       [[k, v.get("state"), v.get("turn"), v.get("note")] for k, v in sorted(omissions.items())]),
        "data/disagreements.csv": csv_text(["point", "state", "turn", "note"],
                                           [[k, v.get("state"), v.get("turn"), v.get("note")] for k, v in sorted(disagreements.items())]),
        "data/limitations.csv": csv_text(["ticket", "claims", "question"],
                                         [[l.get("ticket"), " ".join(l.get("claims") or []), l.get("question")] for l in limitations]),
        "data/revisions.csv": csv_text(["ticket", "answers", "asked", "claims", "input_revision", "output_revision"],
                                       [[r.get("ticket"), answers_of(evidence, r.get("ticket")), asked_of(evidence, r.get("ticket")),
                                         " ".join(r.get("claims") or []), r.get("input_revision"), r.get("output_revision")]
                                        for r in revisions]),
    }

    # figure: the claims as the brief relates them
    nodes = [{"id": c, "label": c, "group": e.get("outline")} for e in entries for c in (e.get("claims") or [])]
    groups = [{"id": e.get("outline"), "label": f"{e.get('outline')} · {e.get('turn')} · {e.get('disposition')}",
               "note": e.get("entry")} for e in entries]
    edges, extra = [], []
    for l in limitations:
        t = l.get("ticket")
        extra.append({"id": t, "label": f"{t} (open)", "kind": "limitation"})
        for c in l.get("claims") or []:
            edges.append({"from": t, "to": c, "kind": "could change"})
    for r in revisions:
        t = r.get("ticket")
        if t and not any(x["id"] == t for x in extra):
            extra.append({"id": t, "label": f"{t} (returned)", "kind": "revision"})
        for c in r.get("claims") or []:
            edges.append({"from": t, "to": c, "kind": "revised"})
    figure = {"id": "fig-claim-map", "kind": "claim-map",
              "title": "The claims in William's order, with what still bears on them",
              "note": ("Relationships as the frozen brief records them. The Interpreter's edge table "
                       "(requires / qualifies / contradicts) is not part of this brief."),
              "groups": groups, "nodes": nodes, "tickets": extra, "edges": edges, "width": 760}

    # markdown with stable section ids and the claim ids as anchors
    md = []
    md.append(f"# {q.get('text') or brief.get('topic') or brief['id']}\n")
    md.append(f"## Question and boundary {{#sec-question}}\n")
    md.append("| | |\n|---|---|")
    md.append(f"| Governing question | {q.get('text') or ''} (revision {q.get('revision')}"
              + (f", set at turn {q['turn']}" if q.get('turn') else "") + ") |")
    md.append(f"| Audience | {brief.get('audience') or ''} |")
    md.append(f"| Reading budget | {brief.get('reading_budget') or ''} |")
    md.append(f"| Authorised | brief `{brief['id']}`, turn `{brief.get('authorized_by_turn')}`, write ticket `{ticket['id']}` |")
    md.append(f"| Conversation | session `{brief['session']}`, {((brief.get('conversation_revision') or {}).get('turns'))} turns at the freeze |")
    md.append("")
    md.append("<!-- Writer: state the boundary here (every term defined, what the page leaves out) before the claims. -->\n")

    md.append("## The argument in William's order {#sec-claims}\n")
    md.append("![The claims in William's order, with what still bears on them](figures/claim-map.json)\n")
    md.append("![Claims as the brief orders them](data/claims.csv)\n")
    for i, e in enumerate(entries, 1):
        oid = e.get("outline")
        md.append(f"### {i}. {e.get('entry')} {{#sec-{oid}}}\n")
        md.append(f"Outline entry `{oid}` from turn `{e.get('turn')}` ({e.get('disposition')}). "
                  f"Claims: " + ", ".join(f"[{c}](#claim-{c})" for c in (e.get("claims") or [])) + ".\n")
        qual = next((x.get("scope") for x in quals if x.get("id") == oid), None)
        if qual:
            md.append(f"> Qualification that stays attached: {qual}\n")
        md.append("*Text to be written by the Writer from the evidence named in the claim register. "
                  "Keep each qualification beside the claim it limits.*\n")

    md.append("## Claim register {#sec-claim-register}\n")
    for c in order:
        md.append(f"### {c} {{#claim-{c}}}\n")
        where = [e.get("outline") for e in entries if c in (e.get("claims") or [])]
        md.append(f"- Appears in: {', '.join(f'[{w}](#sec-{w})' for w in where)}")
        qs = [x.get("scope") for x in quals if c in (x.get("claims") or []) and x.get("scope")]
        for s in qs:
            md.append(f"- Qualification: {s}")
        for l in limitations:
            if c in (l.get("claims") or []):
                md.append(f"- Could still change: ticket `{l.get('ticket')}` is open ({l.get('question')})")
        for r in revisions:
            if c in (r.get("claims") or []):
                md.append(f"- Revised by: ticket `{r.get('ticket')}` (evidence `{r.get('input_revision')}`, result `{r.get('output_revision')}`)")
        if not qs and not any(c in (l.get("claims") or []) for l in limitations) and \
                not any(c in (r.get("claims") or []) for r in revisions):
            md.append("- No qualification, open ticket or revision recorded against this claim in the brief")
        md.append("")

    md.append("## Required qualifications {#sec-qualifications}\n")
    if quals:
        for x in quals:
            md.append(f"- `{x.get('id')}` ({', '.join(x.get('claims') or [])}): {x.get('scope')}")
    else:
        md.append("None recorded in the brief.")
    md.append("")
    md.append("## Deliberate omissions {#sec-omissions}\n")
    md.append("Points William set aside. They stay out of the report; this list says so.\n")
    md.append("![Deferred points](data/omissions.csv)\n" if omissions else "None.\n")
    md.append("## Outstanding disagreements {#sec-disagreements}\n")
    md.append("![Contested points](data/disagreements.csv)\n" if disagreements else "None.\n")
    md.append("## Limitations {#sec-limitations}\n")
    if limitations:
        md.append("William authorised publication while these checks were still open. A later result "
                  "produces a revision proposal; it does not change this edition.\n")
        md.append("![Open tickets at the freeze](data/limitations.csv)\n")
    else:
        md.append("No open ticket touched the lead claims at the freeze.\n")
    md.append("## Evidence and interpretation revisions {#sec-revisions}\n")
    if revisions:
        md.append("The results the conversation had taken in when the brief was frozen. The ticket records "
                  "are kept in `evidence/`.\n")
        md.append("![Results incorporated before the freeze](data/revisions.csv)\n")
    else:
        md.append("No delivered result was incorporated before the freeze.\n")
    if brief.get("figure_ideas"):
        md.append("## Figure ideas from the conversation {#sec-figure-ideas}\n")
        md.append(f"{brief['figure_ideas']}\n")
    md.append("## Sources {#sec-sources}\n")
    srcs = sorted({s for ev in evidence.values()
                   for rec in [ev] + (ev.get("parents") or [])
                   for s in ((rec.get("result") or {}).get("source_refs") or [])})
    if srcs:
        for s in srcs:
            md.append(f"- {s}")
    else:
        md.append("- No source reference was carried by the incorporated results.")
    md.append("")
    return "\n".join(md), data, figure


def cmd_scaffold(a):
    brief_path = Path(a.brief)
    if not brief_path.is_absolute():
        brief_path = ROOT / brief_path
    if not brief_path.is_file():
        refuse(f"no brief at {rel(brief_path)}")
    brief = read_json(brief_path)
    for k in ("id", "session", "authorized_by_turn", "ordered_claims"):
        if k not in brief:
            refuse(f"brief {rel(brief_path)} lacks '{k}'; not a frozen brief from tools/conversationalist.py")
    turn = brief.get("authorized_by_turn")
    if not turn:
        refuse(f"brief {brief['id']} has no authorising turn; publication starts on William's explicit word")
    if not session_turn_exists(brief["session"], turn):
        refuse(f"brief {brief['id']} names turn {turn}, which is not in sessions/{brief['session']}/turns/")
    tid = a.ticket
    tpath = co.ticket_path(tid)
    if not tpath:
        refuse(f"write ticket {tid} is not in the ledger (workflow/outbox/write/{tid}.json); "
               f"the brief has not been handed to the Writer through the Coordinator")
    ticket = read_json(tpath)
    if ticket.get("kind") != "write":
        refuse(f"ticket {tid} is a '{ticket.get('kind')}' ticket, not the brief's write ticket")
    expected_key = f"{brief['session']}/{turn}/{brief['id']}"
    if ticket.get("request_key") != expected_key:
        refuse(f"ticket {tid} has request_key '{ticket.get('request_key')}'; the write ticket for this brief "
               f"carries '{expected_key}'")
    st = co.state_of(tid)
    if st["state"] in ("canceled", "superseded"):
        refuse(f"write ticket {tid} is {st['state']}; the authorisation no longer stands")
    report_id = a.report_id or default_report_id(brief)
    pkg = Package(report_id)
    if pkg.dir.exists():
        refuse(f"reports/{report_id}/ already exists; edit its sources and run freeze, or choose --report-id")

    # evidence: the ledger records of every result the brief incorporated, kept with the package
    evidence = {}
    for r in brief.get("evidence_and_interpretation_revisions") or []:
        t = r.get("ticket")
        if not t:
            continue
        et, res = ticket_result(t)
        if et is not None:
            origin = co.root_question(et)
            chain, seen, cur = [], set(), et
            while cur and cur.get("parent") and cur["parent"] not in seen:      # the research behind the interpretation
                seen.add(cur["id"])
                pt, pres = ticket_result(cur["parent"])
                if pt is None:
                    break
                chain.append({"ticket": pt, "result": pres, "events": co.events_of(pt["id"])})
                cur = pt
            evidence[t] = {"ticket": et, "result": res, "events": co.events_of(t), "parents": chain,
                           "answers": {"id": origin["id"], "question": origin.get("question"),
                                       "origin": origin.get("origin"), "submitted": origin.get("submitted")}}
    locale = a.locale
    md, data, figure = scaffold_sources(brief, ticket, evidence, locale)

    pkg.dir.mkdir(parents=True)
    shutil.copyfile(brief_path, pkg.dir / "brief.json")
    shutil.copyfile(tpath, pkg.dir / "ticket.json")
    write_text(pkg.dir / "publication.md", md)
    for r, text in data.items():
        write_text(pkg.dir / r, text)
    write_json(pkg.dir / "figures" / "claim-map.json", figure)
    for t, ev in evidence.items():
        write_json(pkg.dir / "evidence" / f"{t}.json", ev)
    base = {"brief": {"path": rel(brief_path), "id": brief["id"], "session": brief["session"],
                      "authorized_by_turn": turn, "sha256": sha256_file(brief_path)},
            "write_ticket": {"id": tid, "path": rel(tpath), "request_key": ticket.get("request_key"),
                             "sha256": sha256_file(tpath)},
            "locale": locale, "timezone": "UTC",
            "claims_in_order": claims_in_order(brief),
            "frozen_by": "scaffold", "supersedes_manifest_sha256": None}
    write_json(pkg.manifest_path, pkg.build_manifest(base))
    print(json.dumps({"scaffolded": f"reports/{report_id}/", "report_id": report_id, "brief": brief["id"],
                      "write_ticket": tid, "inputs": len(pkg.manifest()["inputs"]),
                      "claims_in_order": claims_in_order(brief),
                      "next": [f"edit reports/{report_id}/publication.md, data/, figures/",
                               f"python tools/publish.py freeze --report {report_id}",
                               f"python tools/publish.py build --report {report_id}"]},
                     ensure_ascii=False, indent=1))
    return 0


def cmd_freeze(a):
    pkg = Package(a.report)
    old = pkg.manifest()
    # the brief and the ticket are immutable: the copies must still match their originals
    for key, name in (("brief", "brief.json"), ("write_ticket", "ticket.json")):
        src = ROOT / old[key]["path"]
        copy = pkg.dir / name
        if not copy.is_file():
            refuse(f"reports/{pkg.id}/{name} is missing; the package must keep the frozen {key}")
        if src.is_file() and sha256_file(src) != sha256_file(copy):
            refuse(f"reports/{pkg.id}/{name} differs from {old[key]['path']}; the {key} is immutable")
    base = {k: old[k] for k in ("brief", "write_ticket", "locale", "timezone", "claims_in_order")}
    base.update(frozen_by="freeze", supersedes_manifest_sha256=sha256_file(pkg.manifest_path))
    new = pkg.build_manifest(base)
    write_json(pkg.manifest_path, new)
    changed = sorted(r for r in set(new["inputs"]) | set(old["inputs"])
                     if (new["inputs"].get(r) or {}).get("sha256") != (old["inputs"].get(r) or {}).get("sha256"))
    print(json.dumps({"frozen": f"reports/{pkg.id}/manifest.json", "inputs": len(new["inputs"]),
                      "changed_since_previous": changed, "manifest_sha256": sha256_file(pkg.manifest_path)},
                     ensure_ascii=False, indent=1))
    return 0


# ---------------------------------------------------------------- rendering: markdown subset
INLINE_CODE = re.compile(r"`([^`]+)`")
INLINE_BOLD = re.compile(r"\*\*(.+?)\*\*")
INLINE_EM = re.compile(r"(?<![*\w])\*([^*\n]+?)\*(?![*\w])")
INLINE_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*(?:\{#([A-Za-z0-9_.:-]+)\})?\s*$")
IMAGE = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)\s*$")
CLAIM_ID = re.compile(r"\b(C-\d+)\b")


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "section"


def inline(text, anchors):
    t = esc(text)
    t = INLINE_CODE.sub(lambda m: f"<code>{m.group(1)}</code>", t)
    t = INLINE_BOLD.sub(r"<strong>\1</strong>", t)
    t = INLINE_EM.sub(r"<em>\1</em>", t)

    def link(m):
        href = m.group(2)
        anchors.append(href)
        return f'<a href="{href}">{m.group(1)}</a>'
    t = INLINE_LINK.sub(link, t)
    # bare claim ids become marked spans that link to their register entry (not inside code/links)
    parts = re.split(r"(<code>.*?</code>|<a .*?</a>)", t)
    for i in range(0, len(parts), 2):
        parts[i] = CLAIM_ID.sub(lambda m: f'<span class="claim">{m.group(1)}</span>', parts[i])
    return "".join(parts)


def render_table_rows(header, rows, anchors, table_id):
    h = "".join(f"<th>{inline(c, anchors)}</th>" for c in header)
    body = "".join("<tr>" + "".join(f"<td>{inline(c, anchors)}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="scroll"><table id="{esc(table_id)}"><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table></div>'


def render_csv(path, caption, anchors):
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
    if not rows:
        return f'<p class="placeholder">{esc(caption)}: empty table</p>'
    header, body = rows[0], rows[1:]
    if not body:
        return f'<p class="placeholder">{esc(caption)}: no rows</p>'
    tid = "tbl-" + slug(path.stem)
    return (f'<figure id="fig-{slug(path.stem)}">{render_table_rows(header, body, anchors, tid)}'
            f'<figcaption>{inline(caption, anchors)} <code>{esc(path.name)}</code></figcaption></figure>')


def render_figure(path, caption, anchors):
    spec = read_json(path)
    if spec.get("kind") != "claim-map":
        return f'<p class="placeholder">figure kind {esc(spec.get("kind"))} has no renderer</p>'
    return (f'<figure id="{esc(spec.get("id") or "fig-" + slug(path.stem))}">{svg_claim_map(spec)}'
            f'<figcaption>{inline(caption, anchors)}'
            + (f" {esc(spec['note'])}" if spec.get("note") else "") + "</figcaption></figure>")


def svg_claim_map(spec):
    """Deterministic grid: one row per outline entry (its claims side by side), then one row of
    ticket boxes, with straight edges from each ticket to the claims it bears on."""
    font = ", ".join(FONT_STACK)
    nw, nh, gap, pad, left, top = 112, 34, 14, 10, 16, 16
    group_h = nh + 2 * pad + 18
    groups = spec.get("groups") or []
    nodes = spec.get("nodes") or []
    tickets = spec.get("tickets") or []
    edges = spec.get("edges") or []
    width = max(int(spec.get("width") or 760),
                left * 2 + max([pad * 2 + len([n for n in nodes if n["group"] == g["id"]]) * (nw + gap) for g in groups] + [0]),
                left * 2 + len(tickets) * (nw + gap))
    pos, parts = {}, []
    y = top
    for g in groups:
        members = [n for n in nodes if n.get("group") == g["id"]]
        gw = max(nw, pad * 2 + len(members) * (nw + gap) - gap)
        parts.append(f'<rect x="{left}" y="{y}" width="{width - 2 * left}" height="{group_h}" rx="6" '
                     f'fill="var(--card, #f6f6f4)" stroke="var(--rule, #cfcfcf)"/>')
        parts.append(f'<text x="{left + pad}" y="{y + 14}" font-size="12" fill="var(--muted, #5a5a5a)">{esc(g.get("label"))}</text>')
        x = left + pad
        for n in members:
            ny = y + 20 + pad // 2
            pos[n["id"]] = (x + nw / 2, ny, ny + nh)
            parts.append(f'<a href="#claim-{esc(n["id"])}"><rect x="{x}" y="{ny}" width="{nw}" height="{nh}" rx="5" '
                         f'fill="var(--tint, #eef3fb)" stroke="var(--accent, #1d5fb8)" stroke-width="1.5"/>'
                         f'<text x="{x + nw / 2}" y="{ny + nh / 2 + 5}" font-size="14" font-weight="700" text-anchor="middle" '
                         f'fill="var(--ink, #1b1b1b)">{esc(n.get("label"))}</text></a>')
            x += nw + gap
        note = (g.get("note") or "")
        room = width - left - pad - x - 4
        if note and room > 60:
            budget = int(room / 6.6)                      # about 6.6 px per character at 12 px
            shown = note if len(note) <= budget else note[:max(1, budget - 1)] + "…"
            parts.append(f'<text x="{x + 4}" y="{y + 20 + pad // 2 + nh / 2 + 5}" font-size="12" '
                         f'fill="var(--muted, #5a5a5a)">{esc(shown)}</text>')
        y += group_h + gap
    if tickets:
        ty = y + 30
        taken = []                                        # x positions already used in the ticket row
        for t in tickets:
            targets = [e["to"] for e in edges if e.get("from") == t["id"] and e.get("to") in pos]
            want = (pos[targets[0]][0] - nw / 2) if targets else left + pad
            x = max(left + pad, min(want, width - left - pad - nw))
            while any(abs(x - u) < nw + gap for u in taken):
                x += nw + gap
            taken.append(x)
            colour = "var(--warn, #b25a12)" if t.get("kind") == "limitation" else "var(--accent, #1d5fb8)"
            parts.append(f'<rect x="{x}" y="{ty}" width="{nw}" height="{nh}" rx="5" fill="none" stroke="{colour}" '
                         f'stroke-dasharray="{"4 3" if t.get("kind") == "limitation" else "none"}" stroke-width="1.5"/>'
                         f'<text x="{x + nw / 2}" y="{ty + nh / 2 + 5}" font-size="12" text-anchor="middle" '
                         f'fill="var(--ink, #1b1b1b)">{esc(t.get("label"))}</text>')
            pos[t["id"]] = (x + nw / 2, ty, ty + nh)
        for e in edges:
            if e.get("from") in pos and e.get("to") in pos:
                fx, fy, _ = pos[e["from"]]
                tx, _, tb = pos[e["to"]]
                colour = "var(--warn, #b25a12)" if e.get("kind") == "could change" else "var(--accent, #1d5fb8)"
                parts.append(f'<line x1="{fx}" y1="{fy}" x2="{tx}" y2="{tb}" stroke="{colour}" stroke-width="1.2"/>'
                             f'<text x="{fx + 6}" y="{fy - 5}" font-size="11" fill="{colour}">{esc(e.get("kind"))}</text>')
        y = ty + nh + 10
    height = y + top
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
            f'font-family="{esc(font)}" role="img" aria-label="{esc(spec.get("title"))}">'
            f'<title>{esc(spec.get("title"))}</title>' + "".join(parts) + "</svg>")


def render_markdown(md, pkg_dir, anchors, ids, headings):
    lines = md.split("\n")
    out, i, para = [], 0, []

    def flush():
        if para:
            out.append(f"<p>{inline(' '.join(para), anchors)}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            flush(); i += 1; continue
        if s.startswith("<!--"):
            flush()
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1
            continue
        m = HEADING.match(s)
        if m:
            flush()
            level = len(m.group(1))
            hid = m.group(3) or slug(m.group(2))
            ids.add(hid)
            text = inline(m.group(2), anchors)
            if level > 1:
                headings.append((level, hid, m.group(2)))
                out.append(f'<h{level} id="{esc(hid)}">{text}<a class="anchor" href="#{esc(hid)}">#{esc(hid)}</a></h{level}>')
            else:
                out.append(f'<h{level} id="{esc(hid)}">{text}</h{level}>')
            i += 1
            continue
        m = IMAGE.match(s)
        if m:
            flush()
            target = (pkg_dir / m.group(2))
            if not target.is_file():
                out.append(f'<p class="placeholder">missing figure or data file: {esc(m.group(2))}</p>')
                anchors.append("MISSING:" + m.group(2))
            elif target.suffix == ".csv":
                out.append(render_csv(target, m.group(1), anchors))
            elif target.suffix == ".json":
                out.append(render_figure(target, m.group(1), anchors))
            else:
                out.append(f'<figure><img src="{esc(m.group(2))}" alt="{esc(m.group(1))}"><figcaption>{esc(m.group(1))}</figcaption></figure>')
            i += 1
            continue
        if s.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                out.append(render_table_rows(rows[0], rows[1:], anchors, f"tbl-{len(out)}"))
            continue
        if s.startswith("- "):
            flush()
            items = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:])
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(it, anchors)}</li>" for it in items) + "</ul>")
            continue
        if s.startswith("> "):
            flush()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            out.append(f'<blockquote class="limitation">{inline(" ".join(quote), anchors)}</blockquote>')
            continue
        para.append(s)
        i += 1
    flush()
    return "\n".join(out)


def render_html(pkg, manifest):
    md = (pkg.dir / "publication.md").read_text(encoding="utf-8")
    anchors, ids, headings = [], set(), []
    body = render_markdown(md, pkg.dir, anchors, ids, headings)
    for c in manifest.get("claims_in_order") or []:
        ids.add(f"claim-{c}") if f'id="claim-{c}"' in body else None
    title_m = re.search(r"<h1[^>]*>(.*?)</h1>", body)
    title = re.sub(r"<[^>]+>", "", title_m.group(1)) if title_m else pkg.id
    toc = "".join(f'<li><a href="#{esc(h[1])}">{esc(h[2])}</a></li>' for h in headings if h[0] == 2)
    b, t = manifest["brief"], manifest["write_ticket"]
    kicker = (f"Report <code>{esc(pkg.id)}</code> · brief <code>{esc(b['id'])}</code> of session <code>{esc(b['session'])}</code> · "
              f"authorised at turn <code>{esc(b['authorized_by_turn'])}</code> · write ticket <code>{esc(t['id'])}</code>")
    doc = (f'<!doctype html>\n<html lang="{esc(manifest.get("locale") or "en")}">\n<head>\n<meta charset="utf-8">\n'
           f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>{title}</title>\n'
           f'<link rel="stylesheet" href="report.css">\n</head>\n<body>\n'
           f'<header class="report"><div class="kicker">{kicker}</div></header>\n'
           f'<nav class="toc"><strong>Contents</strong><ol>{toc}</ol></nav>\n<main>\n{body}\n</main>\n'
           f'<footer class="report">Built by tools/publish.py {PUBLISH_VERSION} from reports/{esc(pkg.id)}/manifest.json '
           f'(sha256 {sha256_file(pkg.manifest_path)[:16]}…). Sources: the frozen brief, its write ticket, the data and '
           f'figure files in the package. Editions are generated outside git and can be rebuilt from those sources.</footer>\n'
           f'</body>\n</html>\n')
    # link check: every internal anchor must exist; every local reference must exist
    bad_anchors = sorted({h[1:] for h in anchors if h.startswith("#") and h[1:] not in ids})
    missing_refs = sorted({h[len("MISSING:"):] for h in anchors if h.startswith("MISSING:")})
    return doc, {"anchors_checked": len([h for h in anchors if h.startswith("#")]), "broken_anchors": bad_anchors,
                 "missing_files": missing_refs, "sections": [h[1] for h in headings]}


# ---------------------------------------------------------------- rendering: pdf via the vault's renderer
PDF_VOLATILE = [(re.compile(rb"/CreationDate \(D:[^)]*\)"), b"/CreationDate (D:0)"),
                (re.compile(rb"/ModDate \(D:[^)]*\)"), b"/ModDate (D:0)"),
                (re.compile(rb"/ID \[<[0-9A-Fa-f]+> <[0-9A-Fa-f]+>\]"), b"/ID [<0> <0>]")]


def normalise_pdf(b):
    for rx, rep in PDF_VOLATILE:
        b = rx.sub(rep, b)
    return b


def pdf_renderer():
    """The renderer tools/build_platform_pilot.py already uses: Python Playwright driving the
    installed Chrome. Returns (ok, detail). Nothing is installed or downloaded here."""
    chrome = os.environ.get("CHROME_PATH") or CHROME_DEFAULT
    missing = []
    try:
        import importlib.metadata
        from playwright.sync_api import sync_playwright  # noqa: F401
        pw_version = importlib.metadata.version("playwright")
    except Exception as e:
        missing.append(f"Python package 'playwright' is not importable ({type(e).__name__}); "
                       f"tools/build_platform_pilot.py uses it, see modules/platforms/README.md")
        pw_version = None
    if not Path(chrome).is_file():
        missing.append(f"Chrome not found at {chrome} (set CHROME_PATH)")
    return (not missing), {"chrome_path": chrome, "playwright": pw_version, "missing": missing}


def print_pdf(html_path, pdf_path, manifest):
    from playwright.sync_api import sync_playwright
    ok, detail = pdf_renderer()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=detail["chrome_path"], headless=True)
        ctx = browser.new_context(viewport={"width": PAGE["width_px"], "height": 900}, device_scale_factor=1,
                                  locale=manifest.get("locale") or "en-US", timezone_id=manifest.get("timezone") or "UTC",
                                  color_scheme="light")
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
        page.goto(Path(html_path).as_uri(), wait_until="load")
        page.evaluate("document.fonts.ready")
        overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
        page.pdf(path=str(pdf_path), format=PAGE["size"], print_background=True, prefer_css_page_size=True)
        version = browser.version
        ctx.close()
        browser.close()
    return {"engine": f"Chromium {version} via Python Playwright {detail['playwright']}", "page_errors": errors,
            "desktop_overflow": overflow, "os": f"{platform.system()} {platform.release()}"}


# ---------------------------------------------------------------- build / verify
def build_edition(pkg, manifest, out_dir, want_pdf):
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    doc, checks = render_html(pkg, manifest)
    write_text(out_dir / "index.html", doc)
    write_text(out_dir / "report.css", THEME_CSS)
    record = {"report_id": pkg.id, "manifest_sha256": sha256_file(pkg.manifest_path),
              "renderer": {"name": "tools/publish.py", "version": PUBLISH_VERSION},
              "inputs": manifest["inputs"], "locale": manifest.get("locale"), "timezone": manifest.get("timezone"),
              "html": {"file": "index.html", "sha256": sha256_file(out_dir / "index.html")},
              "css": {"file": "report.css", "sha256": sha256_file(out_dir / "report.css")},
              "checks": checks, "pdf": None}
    ok, detail = pdf_renderer()
    if want_pdf and ok:
        info = print_pdf(out_dir / "index.html", out_dir / "index.pdf", manifest)
        raw = (out_dir / "index.pdf").read_bytes()
        record["pdf"] = {"file": "index.pdf", "produced": True, "normalised_sha256": sha256_bytes(normalise_pdf(raw)),
                         "bytes": len(raw), **info}
    elif want_pdf:
        record["pdf"] = {"produced": False, "missing": detail["missing"],
                         "note": "PDF skipped: the existing renderer is not available on this machine; nothing was installed"}
    else:
        record["pdf"] = {"produced": False, "missing": [], "note": "PDF not requested (--no-pdf)"}
    write_json(out_dir / "build.json", record)
    return record


def cmd_build(a):
    pkg = Package(a.report)
    manifest = pkg.manifest()
    pkg.refuse_unless_intact(manifest, "build")
    out_dir = Path(a.out) if a.out else OUTPUT / pkg.id / a.edition
    rec = build_edition(pkg, manifest, out_dir, not a.no_pdf)
    problems = rec["checks"]["broken_anchors"] or rec["checks"]["missing_files"] or \
        (rec["pdf"] or {}).get("page_errors") or (rec["pdf"] or {}).get("desktop_overflow")
    if not a.out:
        eds = [e for e in pkg.editions() if e["edition"] != a.edition]
        eds.append({"edition": a.edition, "output": rel(out_dir), "manifest_sha256": rec["manifest_sha256"],
                    "html_sha256": rec["html"]["sha256"], "css_sha256": rec["css"]["sha256"],
                    "pdf": {k: (rec["pdf"] or {}).get(k) for k in ("produced", "normalised_sha256", "engine", "missing")},
                    "renderer_version": PUBLISH_VERSION, "built_from_ticket": manifest["write_ticket"]["id"]})
        write_json(pkg.dir / "editions.json", sorted(eds, key=lambda e: e["edition"]))
    print(json.dumps({"built": rel(out_dir), "edition": a.edition, "html_sha256": rec["html"]["sha256"],
                      "pdf": rec["pdf"], "checks": rec["checks"], "problems": bool(problems)}, ensure_ascii=False, indent=1))
    return 1 if problems else 0


def compare_dirs(published, rebuilt):
    files = sorted({p.name for p in Path(published).iterdir() if p.is_file()} |
                   {p.name for p in Path(rebuilt).iterdir() if p.is_file()})
    rows = []
    for name in files:
        a, b = Path(published) / name, Path(rebuilt) / name
        if not a.is_file() or not b.is_file():
            rows.append({"file": name, "same": False, "why": "missing in " + ("published edition" if not a.is_file() else "rebuild")})
            continue
        ab, bb = a.read_bytes(), b.read_bytes()
        if name.endswith(".pdf"):
            same = normalise_pdf(ab) == normalise_pdf(bb)
            rows.append({"file": name, "same": same, "compared": "bytes after normalising volatile metadata",
                         "published_sha256": sha256_bytes(normalise_pdf(ab)), "rebuilt_sha256": sha256_bytes(normalise_pdf(bb))})
        else:
            rows.append({"file": name, "same": ab == bb, "compared": "bytes",
                         "published_sha256": sha256_bytes(ab), "rebuilt_sha256": sha256_bytes(bb)})
    return rows


def cmd_verify(a):
    pkg = Package(a.report)
    manifest = pkg.manifest()
    pkg.refuse_unless_intact(manifest, "verify")          # names the missing input precisely, exit 3
    ed = next((e for e in pkg.editions() if e["edition"] == a.edition), None)
    if not ed:
        refuse(f"no edition '{a.edition}' recorded in reports/{pkg.id}/editions.json")
    published = ROOT / ed["output"]
    if not published.is_dir():
        refuse(f"published edition directory is gone: {ed['output']} (disposable output; rebuild with "
               f"`python tools/publish.py build --report {pkg.id} --edition {a.edition}`)", 5)
    stale = ed["manifest_sha256"] != sha256_file(pkg.manifest_path)
    second = Path(a.second) if a.second else OUTPUT / pkg.id / f"{a.edition}.verify"
    rec = build_edition(pkg, manifest, second, want_pdf=(ed.get("pdf") or {}).get("produced", False))
    rows = compare_dirs(published, second)
    if not a.keep:
        shutil.rmtree(second, ignore_errors=True)
    identical = all(r["same"] for r in rows) and not stale
    print(json.dumps({"verified": identical, "report": pkg.id, "edition": a.edition, "published": ed["output"],
                      "rebuilt_into": rel(second), "manifest_unchanged_since_build": not stale,
                      "files": rows, "pdf": rec["pdf"]}, ensure_ascii=False, indent=1))
    return 0 if identical else 1


# ---------------------------------------------------------------- revise
def find_result(ref):
    """A later result: a ticket id, or sessions/<S>/inbox.jsonl:<n> (1-based line)."""
    m = re.fullmatch(r"(?:sessions/)?([A-Za-z0-9._-]+)/inbox(?:\.jsonl)?:(\d+)", ref)
    if m:
        p = SESSIONS / m.group(1) / "inbox.jsonl"
        items = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.is_file() else []
        n = int(m.group(2))
        if not 0 < n <= len(items):
            refuse(f"no inbox item {n} in sessions/{m.group(1)}/inbox.jsonl ({len(items)} items)")
        item = items[n - 1]
        return {"kind": "inbox", "ref": f"sessions/{m.group(1)}/inbox.jsonl:{n}", "ticket": item.get("ticket"),
                "answers": item.get("answers"), "asked": item.get("asked"), "asked_at": item.get("asked_at"),
                "origin": item.get("origin"), "question_revision": item.get("question_revision"),
                "delivered_at": item.get("at"), "result": item.get("result") or {}}
    ticket, result = ticket_result(ref)
    if ticket is None:
        refuse(f"no ticket {ref} in the ledger and not an inbox reference (sessions/<S>/inbox.jsonl:<n>)")
    if result is None:
        refuse(f"ticket {ref} has not finished; a revision proposal needs a landed result")
    origin = co.root_question(ticket)
    return {"kind": "ticket", "ref": ref, "ticket": ticket["id"], "answers": origin["id"], "asked": origin.get("question"),
            "asked_at": origin.get("submitted"), "origin": origin.get("origin"),
            "question_revision": ticket.get("question_revision"), "delivered_at": None, "result": result}


def cmd_revise(a):
    pkg = Package(a.report)
    manifest = pkg.manifest()
    before = {r: sha256_file(pkg.dir / r) for r in pkg.input_files()}
    eds = pkg.editions()
    ed = next((e for e in eds if e["edition"] == a.edition), None) if a.edition else (eds[-1] if eds else None)
    if not ed:
        refuse(f"no published edition to link the proposal to (reports/{pkg.id}/editions.json)")
    res = find_result(a.result)
    r = res["result"]
    changed = r.get("claim_ids_changed") or []
    brief_claims = manifest.get("claims_in_order") or []
    affected = [c for c in brief_claims if c in changed]
    brief = read_json(pkg.dir / "brief.json")
    sections = sorted({f"sec-{e['outline']}" for e in brief.get("ordered_claims") or [] if set(e.get("claims") or []) & set(affected)})
    limitation_closed = [l.get("ticket") for l in brief.get("limitations") or [] if l.get("ticket") in (res["ticket"], res["answers"])]
    revdir = pkg.dir / "revisions"
    n = len(list(revdir.glob("proposal-*.json"))) + 1 if revdir.is_dir() else 1
    pid = f"proposal-{n}"
    material = bool(affected) or bool(limitation_closed)
    proposal = {"id": pid, "report_id": pkg.id, "status": "proposed; the edition stands until William decides",
                "published_edition": {"edition": ed["edition"], "output": ed["output"], "html_sha256": ed["html_sha256"],
                                      "pdf": ed.get("pdf"), "manifest_sha256": ed["manifest_sha256"]},
                "brief": manifest["brief"], "write_ticket": manifest["write_ticket"]["id"],
                "later_result": res, "material": material,
                "affected_claims": affected, "affected_sections": sections + (["claim-" + c for c in affected]),
                "closes_limitation": limitation_closed,
                "claims_changed_outside_brief": [c for c in changed if c not in brief_claims],
                "proposed_changes": ([f"revise the text of {c} (section claim-{c}) against the result's summary and sources" for c in affected]
                                     + [f"move ticket {t} from Limitations to Evidence and interpretation revisions" for t in limitation_closed]
                                     + (["update data/revisions.csv, figures/claim-map.json, then freeze and build a new edition"] if material else [])
                                     or ["none: the result touches no claim in this brief; recorded for the record"]),
                "rule": "a later material result cannot silently change the approved argument; it is proposed here and "
                        "becomes a new edition only after William accepts (re-authorises) it"}
    write_json(revdir / f"{pid}.json", proposal)
    lines = [f"# Revision proposal {pid} for report {pkg.id}", "",
             f"- Published edition: `{ed['edition']}` at `{ed['output']}` (HTML sha256 `{ed['html_sha256']}`), unchanged",
             f"- Later result: {res['kind']} `{res['ref']}`, ticket `{res['ticket']}`, answering `{res['answers']}`: \"{res['asked']}\"",
             f"- Outcome: {r.get('outcome')}; summary: {r.get('summary')}",
             f"- Claims changed: {', '.join(changed) or 'none'}; in this brief: {', '.join(affected) or 'none'}",
             f"- Sources: {', '.join(r.get('source_refs') or []) or 'none named'}; still open: {r.get('uncertainty') or 'nothing recorded'}",
             f"- Material to the approved argument: {'yes' if material else 'no'}", "", "## Proposed changes", ""]
    lines += [f"- {c}" for c in proposal["proposed_changes"]]
    lines += ["", "The approved argument is not changed by this file. A new edition needs William's word, then "
                  "`freeze` and `build`."]
    write_text(revdir / f"{pid}.md", "\n".join(lines) + "\n")
    after = {r: sha256_file(pkg.dir / r) for r in pkg.input_files()}
    assert before == after, "a proposal must not touch the publication sources"
    print(json.dumps({"proposal": f"reports/{pkg.id}/revisions/{pid}.json", "material": material,
                      "affected_claims": affected, "affected_sections": proposal["affected_sections"],
                      "published_edition_unchanged": ed["output"], "sources_unchanged": True}, ensure_ascii=False, indent=1))
    return 0


# ---------------------------------------------------------------- status
def cmd_status(a):
    rows = []
    if REPORTS.is_dir():
        for d in sorted(REPORTS.iterdir()):
            if not (d / "manifest.json").is_file():
                continue
            pkg = Package(d.name)
            m = pkg.manifest()
            missing, changed, extra = pkg.check_inputs(m)
            rows.append({"report": d.name, "brief": m["brief"]["id"], "session": m["brief"]["session"],
                         "write_ticket": m["write_ticket"]["id"], "inputs": len(m["inputs"]),
                         "intact": not (missing or changed or extra), "missing": missing, "changed": changed, "unlisted": extra,
                         "editions": [{"edition": e["edition"], "output": e["output"],
                                       "present": (ROOT / e["output"]).is_dir(),
                                       "pdf": (e.get("pdf") or {}).get("produced")} for e in pkg.editions()],
                         "proposals": sorted(p.name for p in (d / "revisions").glob("proposal-*.json")) if (d / "revisions").is_dir() else []})
    ok, detail = pdf_renderer()
    print(json.dumps({"packages": rows, "pdf_renderer": {"available": ok, **detail}}, ensure_ascii=False, indent=1))
    return 0


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scaffold")
    s.add_argument("--brief", required=True, help="sessions/<S>/briefs/brief-N.json")
    s.add_argument("--ticket", required=True, help="the write ticket the brief filed (T-00NN)")
    s.add_argument("--report-id", dest="report_id", default=None)
    s.add_argument("--locale", default="en-US")
    s.set_defaults(func=cmd_scaffold)

    f = sub.add_parser("freeze"); f.add_argument("--report", required=True); f.set_defaults(func=cmd_freeze)

    b = sub.add_parser("build")
    b.add_argument("--report", required=True); b.add_argument("--edition", default="v1")
    b.add_argument("--out", default=None, help="build into this directory instead of output/reports/<id>/<edition>/ (not recorded)")
    b.add_argument("--no-pdf", dest="no_pdf", action="store_true")
    b.set_defaults(func=cmd_build)

    v = sub.add_parser("verify")
    v.add_argument("--report", required=True); v.add_argument("--edition", default="v1")
    v.add_argument("--second", default=None, help="directory for the comparison rebuild")
    v.add_argument("--keep", action="store_true", help="keep the comparison rebuild")
    v.set_defaults(func=cmd_verify)

    r = sub.add_parser("revise")
    r.add_argument("--report", required=True)
    r.add_argument("--result", required=True, help="a ticket id, or sessions/<S>/inbox.jsonl:<n>")
    r.add_argument("--edition", default=None, help="the published edition to link (default: the latest)")
    r.set_defaults(func=cmd_revise)

    st = sub.add_parser("status"); st.set_defaults(func=cmd_status)

    a = ap.parse_args()
    raise SystemExit(a.func(a))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
