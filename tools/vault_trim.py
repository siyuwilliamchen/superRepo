"""Trim the vault without losing anything: archive old versions, keep originals once.

Pointer convention (William, 2026-11-20): an original document's bytes live once,
in library/objects/<sha[:2]>/<sha><ext>, with a real verified copy in the local
backup. A path in the vault that must keep working becomes a hard link to that
object (no second copy on disk). A path that is no longer needed is removed; the
registry (catalog/sources/library.jsonl) keeps it as an alias, so `restore`
can put it back. Generated output and old versions are zipped into the backup
folder, verified, then deleted.

Commands (all dry-run unless --apply):
  archive  --spec FILE          zip or move the groups in a JSON spec to the backup, then delete
  links    [--out FILE]         list originals that live pages, reports or build code point to
  pointers --policy FILE        plan, then (--apply) hard-link or remove originals per policy
  restore  --path P [--copy]    put a removed original back at its old path
"""
from pathlib import Path, PurePosixPath
import argparse, collections, datetime as dt, fnmatch, hashlib, json, mimetypes, os, re, shutil, sys, uuid, zipfile
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "catalog" / "sources" / "library.jsonl"
LIBRARY = ROOT / "library"
LOCATIONS = json.loads((ROOT / ".local" / "library-locations.json").read_text(encoding="utf-8"))
BACKUP_ID = "local-originals-2026-11-08"
ORIGINALS_BACKUP = Path(LOCATIONS[BACKUP_ID])
BACKUP_ROOT = ORIGINALS_BACKUP.parent
TODAY = dt.date.today().isoformat()
AUDIT = ROOT / "catalog" / "audits" / TODAY

ORIGINAL_EXT = {".pdf", ".html", ".htm", ".txt", ".xml", ".csv", ".tsv", ".xlsx", ".xls", ".docx", ".doc",
                ".pptx", ".epub", ".zip", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".json",
                ".jsonl", ".mp4", ".parquet"}
EVIDENCE_DIRS = {"sources", "research", "inputs"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", "library"}
LEVEL1_DIRS = {"sources", "research", "inputs", "notes", "planning", "reviews", "replies", "synthesis",
               "storylines", "_versions", "claims", "experiments", "research_blind"}
LOCAL_TOPS = {".local", ".scratchpad", "scratch.local", "output", "catalog", "memory", ".git", "library"}
LIVE_EXT = {".html", ".htm", ".md", ".py", ".js", ".cjs", ".mjs", ".json", ".css", ".ps1"}


def rel(p):
    return Path(p).resolve().relative_to(ROOT).as_posix()


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def log(name, row):
    AUDIT.mkdir(parents=True, exist_ok=True)
    with (AUDIT / name).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def walk(base):
    for dp, dns, fns in os.walk(base):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            yield Path(dp) / fn


def prune_empty(path):
    for dp, dns, fns in os.walk(path, topdown=False):
        try:
            if not os.listdir(dp):
                os.rmdir(dp)
        except OSError:
            pass


# ---------------------------------------------------------------- archive
def expand(group):
    files = []
    for item in group["paths"]:
        p = ROOT / item
        found = [p] if p.is_file() else (sorted(walk(p)) if p.is_dir() else [])
        if not found:
            print(f"  missing: {item}")
        for f in found:
            r = rel(f)
            if any(fnmatch.fnmatch(r, pat) for pat in group.get("exclude", [])):
                continue
            if group.get("only") and not any(fnmatch.fnmatch(r, pat) for pat in group["only"]):
                continue
            files.append(f)
    return files


def archive(spec_path, apply):
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    out_dir = BACKUP_ROOT / f"{TODAY}-trim"
    total_n = total_b = 0
    for g in spec["groups"]:
        files = expand(g)
        size = sum(f.stat().st_size for f in files)
        total_n += len(files); total_b += size
        print(f"{g['name']:48s} {len(files):6d} files {size / 2**20:8.1f} MB  [{g.get('mode', 'zip')}]")
        if not apply or not files:
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        if g.get("mode") == "move":  # already an archive: keep it as is in the backup
            for f in files:
                target = out_dir / g["name"] / rel(f)
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = sha_file(f)
                shutil.copyfile(f, target)
                if sha_file(target) != digest:
                    raise SystemExit(f"copy check failed: {target}")
            where = str(out_dir / g["name"])
        else:
            target = out_dir / f"{g['name']}.zip"
            if target.exists():
                raise SystemExit(f"refusing to overwrite {target}")
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
                for f in files:
                    z.write(f, rel(f))
            with zipfile.ZipFile(target) as z:
                bad = z.testzip()
                names = {i.filename: i.file_size for i in z.infolist()}
            expected = {rel(f): f.stat().st_size for f in files}
            if bad or names != expected:
                raise SystemExit(f"zip check failed for {target}: bad={bad}")
            where = str(target)
        for f in files:
            f.unlink()
        for item in g["paths"]:
            if (ROOT / item).is_dir():
                prune_empty(ROOT / item)
        log("trim-log.jsonl", {"date": TODAY, "group": g["name"], "reason": g.get("reason", ""),
                               "files": len(files), "bytes": size, "backup": where,
                               "paths": g["paths"], "exclude": g.get("exclude", []), "only": g.get("only", [])})
        print(f"  -> archived to {where}, removed from vault")
    print(f"{'TOTAL':48s} {total_n:6d} files {total_b / 2**20:8.1f} MB  ({'applied' if apply else 'dry run'})")


# ---------------------------------------------------------------- links
def evidence_part(r):
    parts = r.split("/")
    for i, p in enumerate(parts[:-1]):
        if p in EVIDENCE_DIRS:
            return i
    return None


def live_files():
    for f in walk(ROOT):
        r = rel(f)
        parts = r.split("/")
        if parts[0] in LOCAL_TOPS or any(p in LEVEL1_DIRS for p in parts[:-1]):
            continue
        if "platforms_v4_stage" in parts or f.suffix.lower() not in LIVE_EXT:
            continue
        if f.stat().st_size > 8 * 2**20:
            continue
        yield f, r


HREF = re.compile(r"""(?:href|src|data-src)\s*=\s*["']([^"'#?]+)""", re.I)
PATHLIKE = re.compile(r"""[^\s"'`<>()\[\]{}|,;=]*(?:sources|research|inputs)/[^\s"'`<>()\[\]{}|,;]+""")
QUOTED = re.compile(r"""["']([^"'\n]{2,120})["']""")


def card_index():
    """Evidence folder name -> list of folder paths (e.g. 'PLAT-REPORT-2026-10-20-images')."""
    idx = collections.defaultdict(list)
    for top in ROOT.iterdir():
        if not top.is_dir() or top.name in LOCAL_TOPS or top.name.startswith("."):
            continue
        for dp, dns, _ in os.walk(top):
            dns[:] = [d for d in dns if d not in SKIP_DIRS and d != "_versions"]
            if Path(dp).name in EVIDENCE_DIRS:
                for d in dns:
                    idx[d].append(Path(dp) / d)
                dns[:] = []
    return idx


def add_target(found, path):
    try:
        path = path.resolve()
        r = path.relative_to(ROOT).as_posix()
    except (ValueError, OSError):
        return
    if evidence_part(r) is None and not path.is_dir():
        return
    if path.is_file():
        found.add(r)
    elif path.is_dir() and evidence_part(r + "/x") is not None:
        n = 0
        for f in walk(path):
            found.add(rel(f)); n += 1
            if n > 5000:
                break


def links():
    found, cards = set(), card_index()
    for f, r in live_files():
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        top = ROOT / r.split("/")[0]
        cands = set(HREF.findall(text)) | set(PATHLIKE.findall(text))
        for c in cands:
            c = unquote(c.strip().strip("\\")).replace("\\", "/")
            if c.startswith(("http:", "https:", "mailto:", "data:", "#")):
                continue
            for base in (f.parent, top, ROOT):
                p = base / c.lstrip("/") if c.startswith("/") else base / c
                if p.exists():
                    add_target(found, p)
                    break
        if f.suffix.lower() in {".py", ".js", ".cjs", ".mjs", ".ps1"}:
            for q in QUOTED.findall(text):  # folder names joined at run time
                for folder in cards.get(q.strip("/"), []):
                    add_target(found, folder)
    return found


# ---------------------------------------------------------------- registry
def load_registry():
    recs = {}
    with REGISTRY.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                recs[r["sha256"]] = r
    return recs


def save_registry(recs):
    payload = "".join(json.dumps(recs[k], ensure_ascii=False, separators=(",", ":")) + "\n"
                      for k in sorted(recs))
    tmp = REGISTRY.with_suffix(".jsonl.partial")
    tmp.write_text(payload, encoding="utf-8", newline="\n")
    tmp.replace(REGISTRY)
    (ORIGINALS_BACKUP / "library.jsonl").write_text(payload, encoding="utf-8", newline="\n")


def module_of(r):
    try:
        mods = json.loads((ROOT / "modules/registry.json").read_text(encoding="utf-8"))["modules"]
        return sorted({m["id"] for m in mods for folder in m["content_roots"] if r.startswith(folder + "/")})
    except Exception:
        return []


def copy_verified(src, dst, digest):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.stat().st_size == os.stat(src).st_size:
        return
    tmp = dst.with_name(dst.name + ".partial-" + uuid.uuid4().hex)
    shutil.copyfile(src, tmp)  # the backup is always a real, separate copy
    if sha_file(tmp) != digest:
        raise RuntimeError(f"backup copy failed verification: {dst}")
    tmp.replace(dst)


# ---------------------------------------------------------------- pointers
def topic_policy(r, policy):
    """Return 'link' (keep the path, as a hard link) or 'compress' (path may be removed) for one file."""
    parts = r.split("/")
    i = evidence_part(r)
    kind, card = parts[i], parts[i + 1] if i + 1 < len(parts) - 1 else ""
    field = parts[0]
    if kind == "inputs" or not card:  # supplied documents, and loose files outside a card folder, stay
        return "link"
    rules = policy["fields"].get(field, {"default": "link"})
    for pat in rules.get("keep", []):
        if fnmatch.fnmatch(card, pat):
            return "link"
    for pat in rules.get("compress", []):
        if fnmatch.fnmatch(card, pat):
            return "compress"
    return rules.get("default", "link")


def plan_pointers(policy, link_all=False):
    if link_all:
        # Dedupe only: every path stays, as a hard link to its library object. Nothing is
        # removed, so the reference scan (which decides removals) is not needed.
        linked = set()
        print("link-all mode: no path will be removed; reference scan skipped")
    else:
        linked = links()
        print(f"live references point to {len(linked)} evidence files")
    rows = []
    for top in sorted(ROOT.iterdir()):
        if not top.is_dir() or top.name in LOCAL_TOPS or top.name.startswith("."):
            continue
        for f in walk(top):
            r = rel(f)
            if evidence_part(r) is None or "/_versions/" in r or f.suffix.lower() not in ORIGINAL_EXT:
                continue
            pol = topic_policy(r, policy)
            st = f.stat()
            keep_small = f.suffix.lower() in {".csv", ".tsv"} or (f.suffix.lower() == ".json" and st.st_size < 2**20)
            action = "link" if (link_all or pol == "link" or r in linked or keep_small) else "remove"
            rows.append({"path": r, "size": st.st_size, "mtime": st.st_mtime, "action": action})
    print(f"hashing {len(rows)} files ...", flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        for row, digest in zip(rows, pool.map(lambda x: sha_file(ROOT / x["path"]), rows)):
            row["sha256"] = digest
    return rows, linked


def pointers(policy_path, apply, plan_path=None, link_all=False):
    policy = json.loads(Path(policy_path).read_text(encoding="utf-8"))
    if plan_path and Path(plan_path).exists():
        rows = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    else:
        rows, linked = plan_pointers(policy, link_all)
        AUDIT.mkdir(parents=True, exist_ok=True)
        (AUDIT / "pointer-plan.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        (AUDIT / "linked-originals.json").write_text(json.dumps(sorted(linked), ensure_ascii=False, indent=0), encoding="utf-8")
    recs = load_registry()
    agg = collections.Counter(); sizes = collections.Counter()
    for row in rows:
        known = "registered" if row["sha256"] in recs else "new"
        agg[(row["action"], known)] += 1; sizes[(row["action"], known)] += row["size"]
    for k in sorted(agg):
        print(f"  {k[0]:7s} {k[1]:10s} {agg[k]:7d} files {sizes[k] / 2**20:9.1f} MB")
    if not apply:
        print("dry run; plan saved to", AUDIT / "pointer-plan.json")
        return
    verified = set()
    done = collections.Counter()
    errors = []
    try:
        for n, row in enumerate(rows, 1):
            path = ROOT / row["path"]
            try:
                st = path.stat()
                if st.st_size != row["size"] or abs(st.st_mtime - row["mtime"]) > 1:
                    raise RuntimeError("changed since planning; skipped")
                digest = row["sha256"]
                rec = recs.get(digest)
                if rec is None:  # new original: the vault file itself becomes the library object
                    key = f"objects/{digest[:2]}/{digest}{path.suffix.lower()}"
                    obj = LIBRARY / key
                    obj.parent.mkdir(parents=True, exist_ok=True)
                    if not obj.exists():
                        os.link(path, obj)
                    rec = recs[digest] = {
                        "id": "sha256-" + digest, "title": path.stem, "title_basis": "filename",
                        "modules": module_of(row["path"]), "sha256": digest, "bytes": row["size"],
                        "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                        "locator": {"provider": "local-library", "key": key}, "availability": "local-only",
                        "source_url": None, "retrieved_at": None, "source_manifests": [], "aliases": [],
                        "previously_tracked_aliases": [],
                        "backup": {"id": BACKUP_ID, "key": key, "verified": TODAY, "restore_verified": True,
                                   "separate_device": False}, "imported": TODAY}
                    verified.add(digest)
                obj = LIBRARY / rec["locator"]["key"]
                if digest not in verified:
                    if not obj.exists() or sha_file(obj) != digest:
                        raise RuntimeError(f"library object missing or wrong: {obj}")
                    verified.add(digest)
                copy_verified(obj, ORIGINALS_BACKUP / rec["backup"]["key"], digest)
                if row["path"] not in rec["aliases"]:
                    rec["aliases"].append(row["path"])
                if row["action"] == "link":
                    if not os.path.samefile(path, obj):
                        tmp = path.with_name(path.name + ".link-" + uuid.uuid4().hex[:8])
                        os.link(obj, tmp)
                        os.replace(tmp, path)
                        done["linked"] += 1
                    else:
                        done["already linked"] += 1
                else:
                    path.unlink()
                    rec.setdefault("removed_aliases", [])
                    if row["path"] not in rec["removed_aliases"]:
                        rec["removed_aliases"].append(row["path"])
                    done["removed"] += 1
            except Exception as e:
                errors.append({"path": row["path"], "error": str(e)})
                done["errors"] += 1
            if n % 1000 == 0:
                print(f"  {n}/{len(rows)} {dict(done)}", flush=True)
                save_registry(recs)
    finally:
        save_registry(recs)
        for top in {r["path"].split("/")[0] for r in rows}:
            for dp, dns, fns in os.walk(ROOT / top, topdown=False):
                if not os.listdir(dp) and any(p in EVIDENCE_DIRS for p in Path(dp).parts):
                    try: os.rmdir(dp)
                    except OSError: pass
        summary = {"date": TODAY, "result": dict(done), "errors": len(errors)}
        log("pointer-log.jsonl", summary)
        if errors:
            (AUDIT / "pointer-errors.json").write_text(json.dumps(errors, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(summary))


def restore(path, copy):
    for rec in load_registry().values():
        if path in rec["aliases"]:
            obj = LIBRARY / rec["locator"]["key"]
            if not obj.exists():
                obj = ORIGINALS_BACKUP / rec["backup"]["key"]
            target = ROOT / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                print("already present:", path); return
            (shutil.copyfile if copy else os.link)(obj, target)
            print(("copied" if copy else "linked"), path, "<-", obj)
            return
    raise SystemExit(f"not in the registry: {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("archive"); a.add_argument("--spec", required=True); a.add_argument("--apply", action="store_true")
    l = sub.add_parser("links"); l.add_argument("--out")
    p = sub.add_parser("pointers"); p.add_argument("--policy", required=True); p.add_argument("--plan")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--link-all", action="store_true",
                   help="dedupe only: keep every path as a hard link, remove nothing, skip the reference scan")
    r = sub.add_parser("restore"); r.add_argument("--path", required=True); r.add_argument("--copy", action="store_true")
    args = ap.parse_args()
    if args.cmd == "archive":
        archive(args.spec, args.apply)
    elif args.cmd == "links":
        found = sorted(links())
        if args.out:
            Path(args.out).write_text(json.dumps(found, ensure_ascii=False, indent=0), encoding="utf-8")
        print(len(found), "evidence files are referenced by live files")
    elif args.cmd == "pointers":
        pointers(args.policy, args.apply, args.plan, args.link_all)
    else:
        restore(args.path, args.copy)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
