#!/usr/bin/env python
"""claimmap: validate, print and diff the Interpreter's claim maps.

Phase 3 of "LiveOS research through conversation" (William's design, 2026-11-25, Draft 1,
section 3 "Interpreter" and the result contract in section 4). The Interpreter writes one
map per revision at topics/<topic>/claims/map-r<N>.json; this tool is the ordinary code
around it: it checks a map's shape, prints it for a reader, and turns two revisions into the
"compact difference from the previous conclusion" that a completion carries back to the
conversation. No model call is made here.

    python tools/claimmap.py validate topics/borrowing-consent/claims/map-r1.json
    python tools/claimmap.py print    topics/borrowing-consent/claims/map-r1.json [--claim C-19]
    python tools/claimmap.py diff     claims/map-r1.json claims/map-r2.json [--json]
    python tools/claimmap.py ids      claims/map-r2.json [--changed-from claims/map-r1.json]
    python tools/claimmap.py latest   topics/borrowing-consent

The format is described in topics/<topic>/claims/FORMAT.md and enforced by validate():

  map        schema_version (1), topic, revision (int >= 1), previous_revision (int or null),
             domain, profile, governing_question, method, source_revisions, written, by,
             claims[], edges[], rivals[], gaps[], requests[]
  claim      id C-NN, title, conclusion, level (R S W V G I U), important (bool),
             status (supported | qualified | open | unverified | not-found),
             evidence[] of {ref, locator, tag, note?}, inference, scope, changes_if,
             missed_if_skipped (required when important), read_here?
  edge       from, relation (requires | qualifies | contradicts | competes with |
             changes the consequence of), to, note?
  rival      id RV-NN, about[] (claim ids), readings[] of {name, conclusion, assumption,
             evidence[]}, differing_assumption, distinguishing_observation,
             status (open | settled), settled_for?
  gap        id U-NN, what, scope_checked, load_bearing (bool), claims[]
  request    kind (research | interpret), question, done_when, claims[]

A claim at level U must say in `scope` or `changes_if` what was checked; the validator
insists on a non-empty `scope`. Nothing here decides what the evidence means: that is the
Interpreter's job, and the map records it so that one link can be challenged by its id.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCHEMA_VERSION = 1
LEVELS = {
    "R": "law or rule text read",
    "S": "primary document read",
    "W": "secondary source",
    "V": "vault card",
    "G": "general knowledge, not checked",
    "I": "inference",
    "U": "looked for, not found",
}
RELATIONS = ("requires", "qualifies", "contradicts", "competes with", "changes the consequence of")
CLAIM_STATUS = ("supported", "qualified", "open", "unverified", "not-found")
RIVAL_STATUS = ("open", "settled")
REQUEST_KINDS = ("research", "interpret")
CLAIM_ID = re.compile(r"^C-\d{2,}$")
RIVAL_ID = re.compile(r"^RV-\d{2,}$")
GAP_ID = re.compile(r"^U-\d{2,}$")

MAP_REQUIRED = ("schema_version", "topic", "revision", "previous_revision", "domain", "profile",
                "governing_question", "method", "source_revisions", "written", "by",
                "claims", "edges", "rivals", "gaps", "requests")
CLAIM_REQUIRED = ("id", "title", "conclusion", "level", "important", "status", "evidence",
                  "inference", "scope", "changes_if")
EVIDENCE_REQUIRED = ("ref", "locator", "tag")
RIVAL_REQUIRED = ("id", "about", "readings", "differing_assumption", "distinguishing_observation", "status")
READING_REQUIRED = ("name", "conclusion", "assumption", "evidence")
GAP_REQUIRED = ("id", "what", "scope_checked", "load_bearing", "claims")
REQUEST_REQUIRED = ("kind", "question", "done_when", "claims")

# The fields of a claim whose change counts as a change of conclusion for the diff.
DIFF_FIELDS = ("conclusion", "level", "status", "important", "scope", "changes_if",
               "missed_if_skipped", "inference")


# ----------------------------------------------------------------------------- loading

def load(path: str | Path) -> dict:
    p = Path(path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"claimmap: no such file: {p}")
    except json.JSONDecodeError as e:
        raise SystemExit(f"claimmap: {p} is not valid JSON: {e}")


def latest_map(topic_dir: str | Path) -> Path | None:
    """The highest-numbered map-r<N>.json under <topic>/claims/, or None."""
    claims = Path(topic_dir) / "claims"
    if not claims.is_dir():
        return None
    best, best_n = None, -1
    for p in claims.glob("map-r*.json"):
        m = re.match(r"map-r(\d+)\.json$", p.name)
        if m and int(m.group(1)) > best_n:
            best, best_n = p, int(m.group(1))
    return best


# ----------------------------------------------------------------------------- validate

def _nonempty_str(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def validate(m: dict) -> list[str]:
    """Return a list of problems. An empty list means the map is well formed."""
    errs: list[str] = []
    if not isinstance(m, dict):
        return ["map is not a JSON object"]
    for k in MAP_REQUIRED:
        if k not in m:
            errs.append(f"map: missing field '{k}'")
    if errs:
        return errs
    if m["schema_version"] != SCHEMA_VERSION:
        errs.append(f"map: schema_version {m['schema_version']!r}, expected {SCHEMA_VERSION}")
    if not (isinstance(m["revision"], int) and m["revision"] >= 1):
        errs.append("map: revision must be an integer >= 1")
    prev = m["previous_revision"]
    if prev is not None and not (isinstance(prev, int) and prev >= 1 and prev < m.get("revision", 0)):
        errs.append("map: previous_revision must be null or an integer below revision")
    for k in ("topic", "domain", "profile", "governing_question", "method", "written"):
        if not _nonempty_str(m[k]):
            errs.append(f"map: '{k}' must be a non-empty string")
    if not isinstance(m["by"], dict) or not _nonempty_str(m["by"].get("worker")):
        errs.append("map: 'by' must name a worker")
    if not isinstance(m["source_revisions"], dict):
        errs.append("map: 'source_revisions' must be an object")
    for k in ("claims", "edges", "rivals", "gaps", "requests"):
        if not isinstance(m[k], list):
            errs.append(f"map: '{k}' must be a list")
    if errs:
        return errs

    ids: set[str] = set()
    for i, c in enumerate(m["claims"]):
        where = f"claims[{i}]" + (f" ({c.get('id')})" if isinstance(c, dict) and c.get("id") else "")
        if not isinstance(c, dict):
            errs.append(f"{where}: not an object")
            continue
        for k in CLAIM_REQUIRED:
            if k not in c:
                errs.append(f"{where}: missing field '{k}'")
        cid = c.get("id")
        if not (isinstance(cid, str) and CLAIM_ID.match(cid)):
            errs.append(f"{where}: id must look like C-07")
        elif cid in ids:
            errs.append(f"{where}: duplicate id {cid}")
        else:
            ids.add(cid)
        if c.get("level") not in LEVELS:
            errs.append(f"{where}: level must be one of {' '.join(LEVELS)}")
        if c.get("status") not in CLAIM_STATUS:
            errs.append(f"{where}: status must be one of {', '.join(CLAIM_STATUS)}")
        if not isinstance(c.get("important"), bool):
            errs.append(f"{where}: important must be true or false")
        for k in ("title", "conclusion", "inference", "scope", "changes_if"):
            if k in c and not _nonempty_str(c[k]):
                errs.append(f"{where}: '{k}' must be a non-empty string")
        if c.get("important") is True and not _nonempty_str(c.get("missed_if_skipped")):
            errs.append(f"{where}: an important claim must say what William would misunderstand "
                        f"if he missed it ('missed_if_skipped')")
        ev = c.get("evidence")
        if not isinstance(ev, list):
            errs.append(f"{where}: evidence must be a list")
        else:
            if c.get("level") != "U" and not ev:
                errs.append(f"{where}: a claim above level U needs at least one evidence reference")
            for j, e in enumerate(ev):
                ew = f"{where}.evidence[{j}]"
                if not isinstance(e, dict):
                    errs.append(f"{ew}: not an object")
                    continue
                for k in EVIDENCE_REQUIRED:
                    if not _nonempty_str(e.get(k)):
                        errs.append(f"{ew}: '{k}' must be a non-empty string")
                if e.get("tag") not in LEVELS:
                    errs.append(f"{ew}: tag must be one of {' '.join(LEVELS)}")
        if c.get("level") == "U" and c.get("status") not in ("not-found", "unverified"):
            errs.append(f"{where}: a level-U claim has status not-found or unverified")

    for i, e in enumerate(m["edges"]):
        where = f"edges[{i}]"
        if not isinstance(e, dict):
            errs.append(f"{where}: not an object")
            continue
        for k in ("from", "relation", "to"):
            if k not in e:
                errs.append(f"{where}: missing field '{k}'")
        if e.get("relation") not in RELATIONS:
            errs.append(f"{where}: relation must be one of: {'; '.join(RELATIONS)}")
        for k in ("from", "to"):
            if k in e and e[k] not in ids:
                errs.append(f"{where}: '{k}' = {e[k]!r} is not a claim id in this map")
        if e.get("from") == e.get("to"):
            errs.append(f"{where}: an edge cannot point at its own claim")

    rids: set[str] = set()
    for i, r in enumerate(m["rivals"]):
        where = f"rivals[{i}]" + (f" ({r.get('id')})" if isinstance(r, dict) and r.get("id") else "")
        if not isinstance(r, dict):
            errs.append(f"{where}: not an object")
            continue
        for k in RIVAL_REQUIRED:
            if k not in r:
                errs.append(f"{where}: missing field '{k}'")
        rid = r.get("id")
        if not (isinstance(rid, str) and RIVAL_ID.match(rid)):
            errs.append(f"{where}: id must look like RV-01")
        elif rid in rids:
            errs.append(f"{where}: duplicate id {rid}")
        else:
            rids.add(rid)
        for cid in r.get("about", []) or []:
            if cid not in ids:
                errs.append(f"{where}: about = {cid!r} is not a claim id in this map")
        readings = r.get("readings")
        if not isinstance(readings, list) or len(readings) < 2:
            errs.append(f"{where}: a rival needs at least two readings")
        else:
            for j, rd in enumerate(readings):
                for k in READING_REQUIRED:
                    if k not in rd:
                        errs.append(f"{where}.readings[{j}]: missing field '{k}'")
        if r.get("status") not in RIVAL_STATUS:
            errs.append(f"{where}: status must be open or settled")
        if r.get("status") == "settled" and not _nonempty_str(r.get("settled_for")):
            errs.append(f"{where}: a settled rival names the reading it settled for ('settled_for')")
        for k in ("differing_assumption", "distinguishing_observation"):
            if k in r and not _nonempty_str(r[k]):
                errs.append(f"{where}: '{k}' must be a non-empty string")

    gids: set[str] = set()
    for i, g in enumerate(m["gaps"]):
        where = f"gaps[{i}]" + (f" ({g.get('id')})" if isinstance(g, dict) and g.get("id") else "")
        if not isinstance(g, dict):
            errs.append(f"{where}: not an object")
            continue
        for k in GAP_REQUIRED:
            if k not in g:
                errs.append(f"{where}: missing field '{k}'")
        gid = g.get("id")
        if not (isinstance(gid, str) and GAP_ID.match(gid)):
            errs.append(f"{where}: id must look like U-01")
        elif gid in gids:
            errs.append(f"{where}: duplicate id {gid}")
        else:
            gids.add(gid)
        if not _nonempty_str(g.get("scope_checked")):
            errs.append(f"{where}: a gap must say what scope was checked ('scope_checked')")
        if not isinstance(g.get("load_bearing"), bool):
            errs.append(f"{where}: load_bearing must be true or false")
        for cid in g.get("claims", []) or []:
            if cid not in ids:
                errs.append(f"{where}: claims = {cid!r} is not a claim id in this map")

    for i, q in enumerate(m["requests"]):
        where = f"requests[{i}]"
        if not isinstance(q, dict):
            errs.append(f"{where}: not an object")
            continue
        for k in REQUEST_REQUIRED:
            if k not in q:
                errs.append(f"{where}: missing field '{k}'")
        if q.get("kind") not in REQUEST_KINDS:
            errs.append(f"{where}: kind must be research or interpret")
        for cid in q.get("claims", []) or []:
            if cid not in ids:
                errs.append(f"{where}: claims = {cid!r} is not a claim id in this map")
    return errs


# ----------------------------------------------------------------------------- print

def _short(s: str, n: int = 160) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def render(m: dict, only: str | None = None) -> str:
    out = []
    out.append(f"Claim map: {m['topic']} r{m['revision']}"
               + (f" (previous r{m['previous_revision']})" if m.get("previous_revision") else " (first map)"))
    out.append(f"Domain: {m['domain']}   Profile: {m['profile']}")
    out.append(f"Question: {m['governing_question']}")
    out.append(f"Method: {_short(m['method'], 300)}")
    out.append(f"Written: {m['written']} by {m['by'].get('worker')}"
               + (f" ({m['by'].get('tool')}, {m['by'].get('model')})" if m['by'].get('tool') else ""))
    if m.get("ticket"):
        out.append(f"Ticket: {m['ticket']}")
    out.append("")
    claims = [c for c in m["claims"] if only is None or c["id"] == only]
    if only and not claims:
        return f"claimmap: no claim {only} in this map"
    out.append(f"Claims ({len(m['claims'])}; * = important)")
    for c in claims:
        star = "*" if c.get("important") else " "
        out.append(f"{star} {c['id']} [{c['level']}] {c['status']:<10} {c['title']}")
        out.append(f"      conclusion: {_short(c['conclusion'], 400)}")
        if only:
            out.append(f"      inference:  {_short(c['inference'], 400)}")
            out.append(f"      scope:      {_short(c['scope'], 400)}")
        out.append(f"      changes if: {_short(c['changes_if'], 300)}")
        if c.get("important"):
            out.append(f"      if missed:  {_short(c['missed_if_skipped'], 300)}")
        for e in c.get("evidence", []):
            out.append(f"      [{e['tag']}] {e['ref']} — {e['locator']}" + (f" — {_short(e['note'], 120)}" if e.get("note") else ""))
    if only:
        rel = [e for e in m["edges"] if e["from"] == only or e["to"] == only]
        if rel:
            out.append("")
            out.append("Edges touching this claim")
            for e in rel:
                out.append(f"  {e['from']} —{e['relation']}→ {e['to']}" + (f": {_short(e.get('note', ''), 140)}" if e.get("note") else ""))
        riv = [r for r in m["rivals"] if only in r.get("about", [])]
        for r in riv:
            out.append("")
            out.append(f"Rival {r['id']} ({r['status']}): {' | '.join(rd['name'] for rd in r['readings'])}")
            out.append(f"  differing assumption: {_short(r['differing_assumption'], 300)}")
            out.append(f"  what would tell them apart: {_short(r['distinguishing_observation'], 300)}")
        return "\n".join(out)
    out.append("")
    out.append(f"Edges ({len(m['edges'])})")
    for e in m["edges"]:
        out.append(f"  {e['from']} —{e['relation']}→ {e['to']}" + (f": {_short(e.get('note', ''), 140)}" if e.get("note") else ""))
    out.append("")
    out.append(f"Rival readings ({len(m['rivals'])})")
    for r in m["rivals"]:
        out.append(f"  {r['id']} ({r['status']}) on {', '.join(r['about'])}: "
                   + " | ".join(rd["name"] for rd in r["readings"]))
        out.append(f"      differing assumption: {_short(r['differing_assumption'], 220)}")
        out.append(f"      what would tell them apart: {_short(r['distinguishing_observation'], 220)}")
        if r.get("settled_for"):
            out.append(f"      settled for: {r['settled_for']}")
    out.append("")
    out.append(f"Gaps ({len(m['gaps'])}; ! = load-bearing)")
    for g in m["gaps"]:
        bang = "!" if g.get("load_bearing") else " "
        out.append(f"{bang} {g['id']} {_short(g['what'], 200)}")
        out.append(f"      checked: {_short(g['scope_checked'], 220)}" + (f"   claims: {', '.join(g['claims'])}" if g.get("claims") else ""))
    if m["requests"]:
        out.append("")
        out.append(f"Bounded requests ({len(m['requests'])})")
        for q in m["requests"]:
            out.append(f"  [{q['kind']}] {_short(q['question'], 200)}  (claims {', '.join(q['claims']) or '-'})")
            out.append(f"      done when: {_short(q['done_when'], 200)}")
    return "\n".join(out)


# ----------------------------------------------------------------------------- diff

def _index(items, key="id"):
    return {x[key]: x for x in items if isinstance(x, dict) and key in x}


def _edge_key(e):
    return (e["from"], e["relation"], e["to"])


def diff(old: dict, new: dict) -> dict:
    """The compact difference from the previous conclusion, as data."""
    oc, nc = _index(old.get("claims", [])), _index(new.get("claims", []))
    added = [nc[i] for i in nc if i not in oc]
    removed = [oc[i] for i in oc if i not in nc]
    changed = []
    for i in nc:
        if i in oc:
            fields = {}
            for f in DIFF_FIELDS:
                if oc[i].get(f) != nc[i].get(f):
                    fields[f] = {"from": oc[i].get(f), "to": nc[i].get(f)}
            oe = {(e["ref"], e["locator"]) for e in oc[i].get("evidence", [])}
            ne = {(e["ref"], e["locator"]) for e in nc[i].get("evidence", [])}
            if oe != ne:
                fields["evidence"] = {"added": sorted(ne - oe), "removed": sorted(oe - ne)}
            if fields:
                changed.append({"id": i, "title": nc[i].get("title"), "fields": fields})
    unchanged = [i for i in nc if i in oc and not any(c["id"] == i for c in changed)]

    oedges = {_edge_key(e): e for e in old.get("edges", [])}
    nedges = {_edge_key(e): e for e in new.get("edges", [])}
    edges_added = [nedges[k] for k in nedges if k not in oedges]
    edges_removed = [oedges[k] for k in oedges if k not in nedges]

    orv, nrv = _index(old.get("rivals", [])), _index(new.get("rivals", []))

    def _rival_changed(a, b):
        """A rival changed when its readings, its separating assumption or the observation
        that would settle it changed; status changes are reported separately."""
        return ([r.get("name") for r in a.get("readings", [])] != [r.get("name") for r in b.get("readings", [])]
                or a.get("differing_assumption") != b.get("differing_assumption")
                or a.get("distinguishing_observation") != b.get("distinguishing_observation")
                or sorted(a.get("about", [])) != sorted(b.get("about", [])))

    rivals = {"opened": [nrv[i] for i in nrv if i not in orv],
              "closed": [orv[i] for i in orv if i not in nrv],
              "settled": [nrv[i] for i in nrv if i in orv and orv[i].get("status") != "settled"
                          and nrv[i].get("status") == "settled"],
              "reopened": [nrv[i] for i in nrv if i in orv and orv[i].get("status") == "settled"
                           and nrv[i].get("status") == "open"],
              "changed": [{"id": i, "readings_from": [r.get("name") for r in orv[i].get("readings", [])],
                           "readings_to": [r.get("name") for r in nrv[i].get("readings", [])],
                           "about": nrv[i].get("about", []),
                           "distinguishing_observation": nrv[i].get("distinguishing_observation")}
                          for i in nrv if i in orv and _rival_changed(orv[i], nrv[i])]}
    og, ng = _index(old.get("gaps", [])), _index(new.get("gaps", []))
    gaps = {"opened": [ng[i] for i in ng if i not in og], "closed": [og[i] for i in og if i not in ng]}

    def _req_key(q):
        return (q.get("kind"), q.get("question"))
    oq = {_req_key(q) for q in old.get("requests", [])}
    requests = [q for q in new.get("requests", []) if _req_key(q) not in oq]

    return {
        "topic": new.get("topic"),
        "from_revision": old.get("revision"),
        "to_revision": new.get("revision"),
        "claims": {"added": added, "removed": removed, "changed": changed, "unchanged": unchanged},
        "edges": {"added": edges_added, "removed": edges_removed},
        "rivals": rivals,
        "gaps": gaps,
        "requests_new": requests,
        "claim_ids_changed": sorted({c["id"] for c in added} | {c["id"] for c in removed}
                                    | {c["id"] for c in changed}),
    }


def render_diff(d: dict) -> str:
    """The few lines a completion carries back: what changed, by claim id."""
    out = []
    frm = f"r{d['from_revision']}" if d["from_revision"] else "nothing (first map)"
    out.append(f"{d['topic']}: {frm} → r{d['to_revision']}. "
               f"Claims changed: {', '.join(d['claim_ids_changed']) or 'none'}; "
               f"unchanged: {len(d['claims']['unchanged'])}.")
    for c in d["claims"]["added"]:
        out.append(f"+ {c['id']} [{c['level']}] added: {_short(c['conclusion'], 220)}")
    for c in d["claims"]["removed"]:
        out.append(f"- {c['id']} removed: {_short(c.get('title', ''), 120)}")
    for c in d["claims"]["changed"]:
        parts = []
        f = c["fields"]
        if "conclusion" in f:
            parts.append(f"conclusion was: {_short(f['conclusion']['from'], 160)} → now: {_short(f['conclusion']['to'], 220)}")
        for k in ("level", "status", "important"):
            if k in f:
                parts.append(f"{k} {f[k]['from']} → {f[k]['to']}")
        for k in ("scope", "changes_if", "missed_if_skipped", "inference"):
            if k in f:
                parts.append(f"{k} revised")
        if "evidence" in f:
            ev = f["evidence"]
            parts.append(f"evidence +{len(ev['added'])}/−{len(ev['removed'])}")
        out.append(f"~ {c['id']}: " + "; ".join(parts))
    for e in d["edges"]["added"]:
        out.append(f"+ edge {e['from']} —{e['relation']}→ {e['to']}" + (f": {_short(e.get('note', ''), 120)}" if e.get("note") else ""))
    for e in d["edges"]["removed"]:
        out.append(f"- edge {e['from']} —{e['relation']}→ {e['to']}")
    for r in d["rivals"]["opened"]:
        out.append(f"+ rival {r['id']} opened on {', '.join(r['about'])}: {' | '.join(rd['name'] for rd in r['readings'])}; "
                   f"tell apart by: {_short(r['distinguishing_observation'], 160)}")
    for r in d["rivals"]["changed"]:
        if r["readings_from"] != r["readings_to"]:
            out.append(f"~ rival {r['id']} on {', '.join(r['about'])}: readings now {' | '.join(r['readings_to'])} "
                       f"(were {' | '.join(r['readings_from'])}); tell apart by: {_short(r['distinguishing_observation'], 160)}")
        else:
            out.append(f"~ rival {r['id']} on {', '.join(r['about'])}: assumption or distinguishing observation revised")
    for r in d["rivals"]["settled"]:
        out.append(f"= rival {r['id']} settled for: {r.get('settled_for')}")
    for r in d["rivals"]["reopened"]:
        out.append(f"! rival {r['id']} reopened")
    for r in d["rivals"]["closed"]:
        out.append(f"- rival {r['id']} dropped")
    for g in d["gaps"]["opened"]:
        out.append(f"+ gap {g['id']}{' (load-bearing)' if g.get('load_bearing') else ''}: {_short(g['what'], 160)}")
    for g in d["gaps"]["closed"]:
        out.append(f"- gap {g['id']} closed: {_short(g['what'], 120)}")
    for q in d["requests_new"]:
        out.append(f"→ request [{q['kind']}] {_short(q['question'], 160)} (claims {', '.join(q['claims']) or '-'})")
    if len(out) == 1:
        out.append("No change of conclusion.")
    return "\n".join(out)


# ----------------------------------------------------------------------------- cli

def main(argv=None) -> int:
    # Windows consoles default to a legacy code page; the maps carry arrows and dashes.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="claimmap", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="check a map's shape; exit 1 with the problems listed if it fails")
    v.add_argument("map")
    p = sub.add_parser("print", help="render a map, or one claim with its edges and rivals")
    p.add_argument("map")
    p.add_argument("--claim", default=None)
    d = sub.add_parser("diff", help="the compact difference from the previous revision")
    d.add_argument("old")
    d.add_argument("new")
    d.add_argument("--json", action="store_true")
    i = sub.add_parser("ids", help="comma-separated claim ids, for a completion's --claims")
    i.add_argument("map")
    i.add_argument("--changed-from", default=None)
    la = sub.add_parser("latest", help="path of the highest revision under <topic>/claims/")
    la.add_argument("topic_dir")
    a = ap.parse_args(argv)

    if a.cmd == "validate":
        m = load(a.map)
        errs = validate(m)
        if errs:
            print(f"claimmap: {a.map}: {len(errs)} problem(s)")
            for e in errs:
                print("  - " + e)
            return 1
        print(f"claimmap: {a.map}: ok ({m['topic']} r{m['revision']}, {len(m['claims'])} claims, "
              f"{len(m['edges'])} edges, {len(m['rivals'])} rivals, {len(m['gaps'])} gaps)")
        return 0
    if a.cmd == "print":
        m = load(a.map)
        errs = validate(m)
        if errs:
            print(f"claimmap: warning: {len(errs)} validation problem(s); printing anyway", file=sys.stderr)
        print(render(m, a.claim))
        return 0
    if a.cmd == "diff":
        o, n = load(a.old), load(a.new)
        dd = diff(o, n)
        print(json.dumps(dd, indent=1, ensure_ascii=False) if a.json else render_diff(dd))
        return 0
    if a.cmd == "ids":
        m = load(a.map)
        if a.changed_from:
            print(",".join(diff(load(a.changed_from), m)["claim_ids_changed"]))
        else:
            print(",".join(c["id"] for c in m.get("claims", [])))
        return 0
    if a.cmd == "latest":
        p = latest_map(a.topic_dir)
        if p is None:
            print("")
            return 1
        print(p.as_posix())
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
