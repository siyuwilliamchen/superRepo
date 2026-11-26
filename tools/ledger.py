"""Artifact ledger and Housekeeper for the SiyuOS vault (pilot, 2026-11-26).

The library registry (catalog/sources/library.jsonl, content-hash ids) stays the ledger
for original documents. This tool keeps the ledger for authored and derived material:
one record per managed artifact in ledger/<domain>/artifacts-<xx>.jsonl, keyed by a
stable id (A-xxxxxxxxxx) that survives moves, including moves across domains. Git holds
the revision history; ledger/receipts/<op-key>.json holds one receipt per accepted batch.

Commands (JSON out; LIVEOS_ROOT selects the vault, default: the repo this file is in):
  batch --file F                 apply a staged batch of operations under one op key
  create/modify/move/retire/restore/register   one-operation batches built from flags
  show --id A | --path P         one record, with what it requires and what requires it
  find [--topic T] [--text S] [--ticket T] [--domain D] [--kind K] [--state S]
  requires --id A | required-by --id A [--direct]      the dependency graph, both ways
  hold --id A --job J --ticket T | release --job J     a running job pins an input
  drift [--domain D]             registered path or digest differs from disk or git
  index [--rebuild | --check]    the disposable lookup index in .local/ledger/
  recover                        finish or discard interrupted batches; replay views
  housekeep plan|approve|apply   candidates sorted eligible / held / unresolved; approval
                                 bound to ids and versions; rechecked at apply time
  inventory --domain D --roots P... [--infer-inputs] [--write] [--chain P]
                                 cheap mechanical inventory (bootstrap); dry run by default

Every query prints its measures: index queries, file bodies opened, bytes read, model
calls (always 0). A modify never writes in place: new bytes land in a new file that
replaces the path, so a hard-linked sibling keeps its bytes. Protected roots (inputs/,
the frozen October platform page, git history, the library objects) are refused.
"""
from pathlib import Path
import argparse, datetime as dt, fnmatch, hashlib, json, os, re, shutil, sqlite3, subprocess, sys, time, uuid, zipfile
from contextlib import closing

ROOT = Path(os.environ.get("LIVEOS_ROOT") or Path(__file__).resolve().parents[1]).resolve()
LEDGER = ROOT / "ledger"
RECEIPTS = LEDGER / "receipts"
HOLDS = LEDGER / "holds"
PLANS = LEDGER / "plans"
LOCAL = ROOT / ".local" / "ledger"
INDEX = LOCAL / "index.sqlite3"
PENDING = LOCAL / "pending"
LOCK = LOCAL / "lock"
ROSTER = ROOT / "workflow" / "roster.json"
TRIM = ROOT / "tools" / "vault_trim.py"
LOCATIONS = ROOT / ".local" / "library-locations.json"
BACKUP_ID = "local-originals-2026-11-08"

KINDS = ("original", "findings", "interpretation", "report-source", "dataset", "figure",
         "derivative", "build-code", "unknown")
STATES = ("active", "inventoried", "retired")
POLICIES = ("default", "retain", "approved-edition", "disposable")
COVERAGE = ("reconciled", "unverified")
PROTECTED = ("inputs/**", "*/inputs/**", "**/inputs/**", "Economics/pages/platforms/index.html",
             ".git/**", "library/**", "catalog/sources/library.jsonl", "ledger/**")
SKIP_DIRS = {".git", ".local", ".scratchpad", "node_modules", "__pycache__", "library", "output"}
MEASURES = {"index_queries": 0, "file_bodies_opened": 0, "bytes_read": 0, "model_calls": 0}
CRASH = os.environ.get("LIVEOS_LEDGER_CRASH")      # fault injection for the recovery tests


# ---------------------------------------------------------------- small helpers
def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def today():
    return dt.date.today().isoformat()


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=1))


def fail(msg, code=2):
    print(json.dumps({"error": msg}, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(code)


def crash_point(name):
    if CRASH == name:
        os._exit(3)


def rel(p):
    return Path(p).resolve().relative_to(ROOT).as_posix()


def local_path(value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        fail(f"expected a vault-relative path: {value!r}")
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        fail(f"path leaves the vault: {value}")
    return path


def digest_file(path):
    """Hash a file body. Counted: this is the only place bodies are opened for reading."""
    h = hashlib.sha256()
    MEASURES["file_bodies_opened"] += 1
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            MEASURES["bytes_read"] += len(chunk)
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def glob_match(pattern, path):
    """fnmatch with `**` crossing folders, `*` within one, and roster placeholders `<x>`."""
    pat = re.sub(r"<[^>]+>", "*", pattern)
    out = ""
    i = 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out += "(?:.*/)?"; i += 3
        elif pat.startswith("**", i):
            out += ".*"; i += 2
        elif pat[i] == "*":
            out += "[^/]*"; i += 1
        else:
            out += re.escape(pat[i]); i += 1
    return re.fullmatch(out, path) is not None


def is_protected(path):
    return next((p for p in PROTECTED if glob_match(p, path)), None)


def git(*args):
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                           encoding="utf-8", timeout=30)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def git_revision():
    out = git("rev-parse", "HEAD")
    return "git:" + out.strip() if out else "nogit"


def write_atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex[:8])
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def place_bytes(source, dest):
    """Put the bytes of `source` at `dest` as a NEW file. Never opens `dest` for writing, so a
    hard-linked sibling of the old `dest` keeps its bytes and the old inode is left alone."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(".tmp-" + uuid.uuid4().hex[:8] + dest.suffix)
    shutil.copyfile(source, tmp)
    os.replace(tmp, dest)


def pid_alive(pid):
    try:
        if os.name == "nt":
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


class Lock:
    """One writer at a time. A lock whose holder is dead, or older than 120 s, is broken."""
    def __enter__(self):
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + 15
        while True:
            try:
                fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode()); os.close(fd)
                return self
            except FileExistsError:
                try:
                    holder = LOCK.read_text(encoding="utf-8").strip()
                    if not pid_alive(holder) or time.time() - LOCK.stat().st_mtime > 120:
                        LOCK.unlink(); continue
                except OSError:
                    continue
                if time.time() > deadline:
                    fail("ledger is locked by another writer")
                time.sleep(0.1)

    def __exit__(self, *exc):
        try:
            LOCK.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- records (authoritative)
def shard_of(aid):
    return aid[2:4]


def shard_path(domain, aid):
    return LEDGER / domain / f"artifacts-{shard_of(aid)}.jsonl"


def domain_dirs():
    if not LEDGER.is_dir():
        return []
    return sorted(d for d in LEDGER.iterdir()
                  if d.is_dir() and d.name not in ("receipts", "holds", "plans") and not d.name.startswith("_"))


def load_records():
    recs = {}
    for d in domain_dirs():
        for shard in sorted(d.glob("artifacts-*.jsonl")):
            for line in shard.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    recs[r["id"]] = r
    return recs


def save_records(recs, touched):
    """Rewrite every shard that any touched record belongs to now or belonged to before."""
    shards = {}
    for domain, aid in touched:
        shards[shard_path(domain, aid)] = None
    for p in shards:
        rows = [r for r in recs.values() if shard_path(r["domain"], r["id"]) == p]
        rows.sort(key=lambda r: r["id"])
        if not rows:
            if p.exists():
                p.unlink()
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp-" + uuid.uuid4().hex[:8])
        tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        tmp.replace(p)


def path_owner(recs, path):
    for r in recs.values():
        if r["state"] != "retired" and r.get("path") == path:
            return r
    return None


def load_holds():
    out = {}
    if HOLDS.is_dir():
        for p in sorted(HOLDS.glob("*.json")):
            h = json.loads(p.read_text(encoding="utf-8"))
            out[h["job"]] = h
    return out


def load_roster():
    if ROSTER.is_file():
        return json.loads(ROSTER.read_text(encoding="utf-8")).get("roles", {})
    return {}


def read_json_file(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- the write path
def new_id(op_key, i):
    return "A-" + hashlib.sha256(f"{op_key}:{i}".encode()).hexdigest()[:10]


def check_scope(role, path, roster):
    if not role or role not in roster:
        return None
    writes = roster[role].get("writes", [])
    if not any(glob_match(w, path) for w in writes):
        return f"path {path} is outside the write scope of role {role} ({', '.join(writes)})"
    return None


def normalise_inputs(items, recs):
    out = []
    for it in items or []:
        if isinstance(it, str):
            it = {"id": it}
        aid = it["id"]
        pinned = it.get("digest")
        if aid.startswith("sha256-"):
            out.append({"id": aid, "digest": None, "locator": "library"})
            continue
        if aid not in recs:
            fail(f"input {aid} is not a registered artifact")
        if pinned == "pin":
            pinned = recs[aid]["digest"]
        out.append({"id": aid, "digest": pinned})
    return out


def stage(batch):
    """Persist intent under the op key with deterministic ids; returns the staged batch."""
    for k in ("op_key", "ticket", "ops"):
        if not batch.get(k):
            fail(f"batch needs {k}")
    staged = dict(batch)
    staged["staged_at"] = now()
    staged["revision"] = git_revision()
    for i, op in enumerate(staged["ops"]):
        if op["op"] in ("create", "register") and not op.get("id"):
            op["id"] = new_id(batch["op_key"], i)
        src = op.get("source")
        if src and not op.get("source_digest"):
            p = Path(src)
            if not p.is_absolute():
                p = ROOT / src
            if not p.is_file():
                fail(f"source file missing: {src}")
            op["source_digest"] = digest_file(p)
            op["source_bytes"] = p.stat().st_size
    PENDING.mkdir(parents=True, exist_ok=True)
    write_atomic(PENDING / f"{safe(batch['op_key'])}.json", staged)
    return staged


def safe(key):
    return re.sub(r"[^A-Za-z0-9._-]", "_", key)


def receipt_path(op_key):
    return RECEIPTS / f"{safe(op_key)}.json"


def apply_batch(batch):
    """One effect per op key. Stage -> check -> place bytes -> write records -> receipt -> views."""
    rp = receipt_path(batch["op_key"])
    if rp.is_file():
        r = read_json_file(rp)
        r["already"] = "accepted"
        refresh_views(quiet=True)
        return r
    with Lock():
        if rp.is_file():                          # raced with another writer of the same key
            r = read_json_file(rp); r["already"] = "accepted"; return r
        staged = stage(batch)
        crash_point("after-stage")
        try:
            receipt = integrate(staged)
        except SystemExit:                        # refused: nothing happened, so no intent survives
            (PENDING / f"{safe(batch['op_key'])}.json").unlink(missing_ok=True)
            raise
        write_atomic(rp, receipt)
        crash_point("after-accept")
        try:
            refresh_views()
        except Exception as e:                    # a stale view is browsable; recover replays it
            receipt["views"] = f"stale: {e}"
        (PENDING / f"{safe(batch['op_key'])}.json").unlink(missing_ok=True)
    return receipt


def integrate(staged):
    recs = load_records()
    roster = load_roster()
    role = staged.get("role")
    op_key = staged["op_key"]
    prov = {"at": now(), "op_key": op_key, "ticket": staged["ticket"], "attempt_id": staged.get("attempt_id"),
            "role": role, "run": staged.get("run")}
    results, touched = [], set()

    # 1. check every op before any byte moves
    plan = []
    for op in staged["ops"]:
        kind = op["op"]
        if kind in ("create", "register"):
            path = op["path"]
            local_path(path)
            if (p := is_protected(path)):
                fail(f"{kind} refused: {path} is under protected root {p}")
            if (m := check_scope(role, path, roster)):
                fail(f"{kind} refused: {m}")
            owner = path_owner(recs, path)
            existing = recs.get(op["id"])
            done = existing if existing and existing.get("changed", {}).get("op_key") == op_key else \
                owner if owner and owner.get("changed", {}).get("op_key") == op_key else None
            if done:
                plan.append(("skip", op, done)); continue
            if kind == "create":
                if owner:
                    fail(f"create refused: {path} is already artifact {owner['id']} v{owner['version']}")
                if existing:
                    fail(f"create refused: id {op['id']} exists")
                if not op.get("source") and not (ROOT / path).is_file():
                    fail(f"create refused: no source and nothing at {path}")
            else:  # register
                if owner and not op.get("reconcile"):
                    fail(f"register refused: {path} is already artifact {owner['id']}; use reconcile for drift")
                if not (ROOT / path).is_file():
                    fail(f"register refused: nothing at {path}")
            if op.get("kind", "unknown") not in KINDS:
                fail(f"unknown kind {op.get('kind')}")
            plan.append((kind, op, owner))
        elif kind in ("modify", "move", "retire"):
            r = recs.get(op.get("id") or "")
            if not r:
                fail(f"{kind} refused: unknown artifact {op.get('id')}")
            if r.get("changed", {}).get("op_key") == op_key:
                plan.append(("skip", op, r)); continue
            if op.get("expected_version") is None:
                fail(f"{kind} refused: expected_version is required (stale-writer check)")
            if r["state"] == "retired":
                fail(f"{kind} refused: {r['id']} is retired (v{r['version']}); only restore may bring it back")
            if r["version"] != op["expected_version"]:
                fail(f"{kind} refused: {r['id']} is at v{r['version']}, writer expected v{op['expected_version']}")
            if r.get("path") and is_protected(r["path"]):
                fail(f"{kind} refused: {r['path']} is protected")
            if kind == "modify":
                if (m := check_scope(role, r["path"], roster)):
                    fail(f"modify refused: {m}")
                if op.get("source"):
                    cur = digest_file(ROOT / r["path"]) if (ROOT / r["path"]).is_file() else None
                    # the staged bytes already in place (crash after placing them) are not drift
                    if cur != r["digest"] and cur != op.get("source_digest"):
                        fail(f"modify refused: drift at {r['path']} (record {r['digest']}, disk {cur}); "
                             f"run `ledger.py drift` and register --reconcile first")
            if kind == "move":
                to = op["to"]; local_path(to)
                if (p := is_protected(to)):
                    fail(f"move refused: {to} is under protected root {p}")
                if (m := check_scope(role, to, roster)):
                    fail(f"move refused: {m}")
                if (o := path_owner(recs, to)):
                    fail(f"move refused: {to} is already artifact {o['id']}")
                resumed = (ROOT / to).is_file() and not (ROOT / r["path"]).exists() and digest_file(ROOT / to) == r["digest"]
                if (ROOT / to).exists() and not resumed:
                    fail(f"move refused: something unregistered is at {to}")
            if kind == "retire":
                holds = [h for h in load_holds().values() if h["id"] == r["id"]]
                if holds:
                    fail(f"retire refused: {r['id']} is pinned by job {holds[0]['job']} (ticket {holds[0]['ticket']})")
                consumers = [c for c in required_by_records(recs, r["id"]) if recs[c]["state"] != "retired"]
                if consumers and not op.get("force"):
                    fail(f"retire refused: {r['id']} is required by {', '.join(consumers)}")
                if not op.get("reason"):
                    fail("retire refused: a reason is required")
            plan.append((kind, op, r))
        elif kind == "restore":
            r = recs.get(op.get("id") or "")
            if not r:
                fail(f"restore refused: unknown artifact {op.get('id')}")
            if r.get("changed", {}).get("op_key") == op_key:
                plan.append(("skip", op, r)); continue
            if r["state"] != "retired":
                fail(f"restore refused: {r['id']} is not retired")
            target = op.get("to") or r["path"]
            local_path(target)
            if (o := path_owner(recs, target)) or (ROOT / target).exists():
                who = o["id"] if o else "an unregistered file"
                fail(f"restore refused: path conflict, {target} is now {who}; pass --to <new path>")
            plan.append((kind, op, r))
        else:
            fail(f"unknown op {kind}")

    # 2. apply
    for kind, op, r in plan:
        if kind == "skip":
            results.append({"op": op["op"], "id": r["id"], "version": r["version"], "already": "applied"})
            continue
        if kind in ("create", "register"):
            path = op["path"]
            if op.get("source"):
                src = Path(op["source"]); src = src if src.is_absolute() else ROOT / op["source"]
                place_bytes(src, ROOT / path)
            dig = digest_file(ROOT / path)
            if op.get("source") and dig != op["source_digest"]:
                fail(f"{kind}: bytes at {path} differ from the staged source")
            if kind == "register" and r:          # reconcile: accept an external edit as a new version
                before = r["digest"]
                r.update(digest=dig, bytes=(ROOT / path).stat().st_size, version=r["version"] + 1,
                         changed=dict(prov, provenance="external edit accepted by reconcile", previous_digest=before))
                if op.get("purpose"):
                    r["purpose"] = op["purpose"]; r["state"] = "active"
                if op.get("coverage"):
                    r["coverage"] = op["coverage"]
                touched.add((r["domain"], r["id"]))
                results.append({"op": "reconcile", "id": r["id"], "version": r["version"], "digest": dig})
                continue
            purpose = op.get("purpose") or "unknown"
            rec = {"id": op["id"], "domain": op["domain"], "path": path, "locator": None, "digest": dig,
                   "bytes": (ROOT / path).stat().st_size, "version": 1, "kind": op.get("kind", "unknown"),
                   "topics": op.get("topics") or [], "purpose": purpose, "role": role,
                   "ticket": staged["ticket"], "inputs": normalise_inputs(op.get("inputs"), recs),
                   "links": op.get("links") or [],
                   "state": "active" if (kind == "create" or purpose != "unknown") else "inventoried",
                   "policy": op.get("policy", "default"),
                   "coverage": op.get("coverage", "reconciled" if kind == "create" else "unverified"),
                   "expires": op.get("expires"), "created": dict(prov, how=kind), "changed": dict(prov, how=kind),
                   "retired": None}
            if kind == "register":
                rec["created"]["basis"] = op.get("basis", "mechanical inventory")
            recs[rec["id"]] = rec
            touched.add((rec["domain"], rec["id"]))
            results.append({"op": kind, "id": rec["id"], "version": 1, "path": path, "digest": dig})
        elif kind == "modify":
            if op.get("source"):
                src = Path(op["source"]); src = src if src.is_absolute() else ROOT / op["source"]
                place_bytes(src, ROOT / r["path"])
            dig = digest_file(ROOT / r["path"])
            for f in ("purpose", "kind", "topics", "policy", "coverage", "expires", "links"):
                if f in op and op[f] is not None:
                    r[f] = op[f]
            if "inputs" in op and op["inputs"] is not None:
                r["inputs"] = normalise_inputs(op["inputs"], recs)
            r.update(digest=dig, bytes=(ROOT / r["path"]).stat().st_size, version=r["version"] + 1,
                     state="active" if r["purpose"] != "unknown" else r["state"], changed=dict(prov, how="modify"))
            touched.add((r["domain"], r["id"]))
            results.append({"op": "modify", "id": r["id"], "version": r["version"], "digest": dig})
        elif kind == "move":
            old_domain, old_path = r["domain"], r["path"]
            (ROOT / op["to"]).parent.mkdir(parents=True, exist_ok=True)
            if (ROOT / old_path).exists():
                os.replace(ROOT / old_path, ROOT / op["to"])
            r.update(path=op["to"], domain=op.get("domain") or r["domain"], version=r["version"] + 1,
                     changed=dict(prov, how="move", from_path=old_path, from_domain=old_domain))
            touched.add((old_domain, r["id"])); touched.add((r["domain"], r["id"]))
            results.append({"op": "move", "id": r["id"], "version": r["version"], "from": old_path, "to": op["to"],
                            "domain": r["domain"]})
        elif kind == "retire":
            res = retire_bytes(r, op, op_key)
            r.update(state="retired", version=r["version"] + 1, changed=dict(prov, how="retire"),
                     retired={"at": now(), "reason": op["reason"], "approval": op.get("approval"),
                              "op_key": op_key, "path": r["path"], "restore": res})
            touched.add((r["domain"], r["id"]))
            save_records(recs, touched)           # the tombstone lands the moment the bytes are gone
            results.append({"op": "retire", "id": r["id"], "version": r["version"], "path": r["path"],
                            "backup": res, "logical_bytes": r["bytes"], "physical_bytes_freed": res["physical_bytes_freed"]})
        elif kind == "restore":
            target = op.get("to") or r["path"]
            restore_bytes(r, target)
            r.update(path=target, state="active" if r["purpose"] != "unknown" else "inventoried",
                     version=r["version"] + 1, changed=dict(prov, how="restore", from_backup=r["retired"]["restore"]),
                     retired=None)
            touched.add((r["domain"], r["id"]))
            results.append({"op": "restore", "id": r["id"], "version": r["version"], "path": target})

    save_records(recs, touched)
    return {"receipt": op_key, "ticket": staged["ticket"], "attempt_id": staged.get("attempt_id"), "role": role,
            "run": staged.get("run"), "at": now(), "revision_before": staged["revision"], "results": results,
            "declared_ops": len(staged["ops"]), "views": "refreshed"}


# ---------------------------------------------------------------- retire and restore bytes
def backup_root():
    if not LOCATIONS.is_file():
        return None
    loc = json.loads(LOCATIONS.read_text(encoding="utf-8"))
    return Path(loc[BACKUP_ID]).parent if BACKUP_ID in loc else None


def retire_bytes(r, op, op_key):
    """Zip, verify, delete through tools/vault_trim.py (the existing cleanup mechanism)."""
    path = ROOT / r["path"]
    if not path.is_file():
        fail(f"retire: nothing at {r['path']}")
    cur = digest_file(path)
    if cur != r["digest"]:
        fail(f"retire refused: drift at {r['path']} (record {r['digest']}, disk {cur})")
    nlink = path.stat().st_nlink
    size = path.stat().st_size
    broot = backup_root()
    if not TRIM.is_file() or broot is None:
        fail("retire needs tools/vault_trim.py and .local/library-locations.json at the vault root")
    name = safe(f"{op_key}-{r['id']}")
    spec = PENDING / f"spec-{name}.json"
    write_atomic(spec, {"groups": [{"name": name, "paths": [r["path"]], "reason": op["reason"]}]})
    p = subprocess.run([sys.executable, "-I", str(TRIM), "archive", "--spec", str(spec), "--apply"],
                       cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", timeout=600)
    if p.returncode != 0:
        fail(f"vault_trim archive failed: {p.stdout}\n{p.stderr}")
    zpath = broot / f"{today()}-trim" / f"{name}.zip"
    if not zpath.is_file() or path.exists():
        fail(f"vault_trim did not leave the expected result ({zpath}, path gone={not path.exists()})")
    with zipfile.ZipFile(zpath) as z:
        with z.open(r["path"]) as fh:
            h = hashlib.sha256()
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    if "sha256:" + h.hexdigest() != r["digest"]:
        fail(f"backup verification failed for {r['path']}")
    spec.unlink(missing_ok=True)
    return {"backend": "vault_trim archive", "zip": str(zpath), "member": r["path"], "digest": r["digest"],
            "verified": True, "physical_bytes_freed": size if nlink == 1 else 0, "nlink_before": nlink}


def restore_bytes(r, target):
    ref = (r.get("retired") or {}).get("restore") or {}
    dest = ROOT / target
    if r.get("locator") and str(r["locator"]).startswith("sha256-"):
        p = subprocess.run([sys.executable, "-I", str(TRIM), "restore", "--path", target], cwd=str(ROOT),
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        if p.returncode != 0:
            fail(f"vault_trim restore failed: {p.stdout}\n{p.stderr}")
        return
    if not ref.get("zip"):
        fail(f"restore: {r['id']} has no restore reference")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(".tmp-" + uuid.uuid4().hex[:8])
    with zipfile.ZipFile(ref["zip"]) as z, z.open(ref["member"]) as src, open(tmp, "wb") as out:
        shutil.copyfileobj(src, out)
    if digest_file(tmp) != ref["digest"]:
        tmp.unlink(); fail(f"restore: backup bytes for {r['id']} do not match the recorded digest")
    os.replace(tmp, dest)


# ---------------------------------------------------------------- dependency graph (from records)
def required_by_records(recs, aid, direct=False):
    """Who requires `aid`, through intermediates and across domains. Derived, never stored."""
    rev = {}
    for r in recs.values():
        for i in r.get("inputs", []):
            rev.setdefault(i["id"], []).append(r["id"])
    seen, queue, out = {aid}, [aid], []
    while queue:
        cur = queue.pop(0)
        for c in rev.get(cur, []):
            if c not in seen:
                seen.add(c); out.append(c)
                if not direct:
                    queue.append(c)
    return out


def chain_records(recs, aid, direct=False):
    """[(consumer, requires, pinned)] edges upward from aid, for printing the actual chain."""
    rev = {}
    for r in recs.values():
        for i in r.get("inputs", []):
            rev.setdefault(i["id"], []).append((r["id"], i.get("digest")))
    seen, queue, edges = {aid}, [aid], []
    while queue:
        cur = queue.pop(0)
        for c, pin in rev.get(cur, []):
            edges.append({"consumer": c, "consumer_path": recs[c]["path"], "consumer_domain": recs[c]["domain"],
                          "consumer_state": recs[c]["state"], "requires": cur, "pinned": pin})
            if c not in seen:
                seen.add(c)
                if not direct:
                    queue.append(c)
    return edges


# ---------------------------------------------------------------- the disposable index
SCHEMA = """
CREATE TABLE IF NOT EXISTS artifacts (id TEXT PRIMARY KEY, domain TEXT, shard TEXT, path TEXT, digest TEXT,
  version INTEGER, kind TEXT, state TEXT, purpose TEXT, role TEXT, ticket TEXT, policy TEXT, coverage TEXT,
  expires TEXT, bytes INTEGER, json TEXT);
CREATE INDEX IF NOT EXISTS artifacts_path ON artifacts(path);
CREATE TABLE IF NOT EXISTS topics (id TEXT, topic TEXT);
CREATE TABLE IF NOT EXISTS inputs (consumer TEXT, input TEXT, pinned TEXT);
CREATE INDEX IF NOT EXISTS inputs_input ON inputs(input);
CREATE TABLE IF NOT EXISTS links (src TEXT, dst TEXT);
CREATE TABLE IF NOT EXISTS receipts (key TEXT PRIMARY KEY, ticket TEXT, at TEXT, json TEXT);
CREATE TABLE IF NOT EXISTS holds (job TEXT PRIMARY KEY, id TEXT, ticket TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS shards (path TEXT PRIMARY KEY, sha256 TEXT);
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
"""


class Index:
    def __init__(self, readonly=False):
        INDEX.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(INDEX, timeout=5)
        if not readonly:
            self.db.executescript(SCHEMA)

    def q(self, sql, args=()):
        MEASURES["index_queries"] += 1
        return self.db.execute(sql, args)

    def close(self):
        self.db.commit(); self.db.close()

    def meta(self, key):
        row = self.q("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return row[0] if row else None


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def update_index(rebuild=False):
    """Incremental: reload only the record shards whose bytes changed; receipts and holds whole."""
    if rebuild and INDEX.exists():
        INDEX.unlink()
    ix = Index()
    stats = {"reloaded_shards": 0, "unchanged_shards": 0, "removed_shards": 0, "rebuild": rebuild}
    present = {}
    for d in domain_dirs():
        for shard in sorted(d.glob("artifacts-*.jsonl")):
            present[shard.relative_to(ROOT).as_posix()] = shard
    indexed = dict(ix.q("SELECT path, sha256 FROM shards").fetchall())
    for relp, shard in present.items():
        sha = file_sha(shard)
        if indexed.get(relp) == sha:
            stats["unchanged_shards"] += 1; continue
        stats["reloaded_shards"] += 1
        old = [row[0] for row in ix.q("SELECT id FROM artifacts WHERE shard=?", (relp,)).fetchall()]
        for aid in old:
            ix.q("DELETE FROM artifacts WHERE id=?", (aid,)); ix.q("DELETE FROM topics WHERE id=?", (aid,))
            ix.q("DELETE FROM inputs WHERE consumer=?", (aid,)); ix.q("DELETE FROM links WHERE src=?", (aid,))
        for line in shard.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            ix.q("DELETE FROM artifacts WHERE id=?", (r["id"],))      # an id moved from another shard
            ix.q("DELETE FROM topics WHERE id=?", (r["id"],)); ix.q("DELETE FROM inputs WHERE consumer=?", (r["id"],))
            ix.q("DELETE FROM links WHERE src=?", (r["id"],))
            ix.q("INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (r["id"], r["domain"], relp, r.get("path"), r["digest"], r["version"], r["kind"], r["state"],
                  r.get("purpose"), r.get("role"), r.get("ticket"), r.get("policy"), r.get("coverage"),
                  r.get("expires"), r.get("bytes"), json.dumps(r, ensure_ascii=False)))
            for t in r.get("topics", []):
                ix.q("INSERT INTO topics VALUES (?,?)", (r["id"], t))
            for i in r.get("inputs", []):
                ix.q("INSERT INTO inputs VALUES (?,?,?)", (r["id"], i["id"], i.get("digest")))
            for l in r.get("links", []):
                ix.q("INSERT INTO links VALUES (?,?)", (r["id"], l))
        ix.q("INSERT OR REPLACE INTO shards VALUES (?,?)", (relp, sha))
    for relp in set(indexed) - set(present):
        stats["removed_shards"] += 1
        for (aid,) in ix.q("SELECT id FROM artifacts WHERE shard=?", (relp,)).fetchall():
            ix.q("DELETE FROM artifacts WHERE id=?", (aid,)); ix.q("DELETE FROM topics WHERE id=?", (aid,))
            ix.q("DELETE FROM inputs WHERE consumer=?", (aid,)); ix.q("DELETE FROM links WHERE src=?", (aid,))
        ix.q("DELETE FROM shards WHERE path=?", (relp,))
    ix.q("DELETE FROM receipts"); ix.q("DELETE FROM holds")
    if RECEIPTS.is_dir():
        for p in sorted(RECEIPTS.glob("*.json")):
            r = read_json_file(p)
            ix.q("INSERT OR REPLACE INTO receipts VALUES (?,?,?,?)", (r["receipt"], r["ticket"], r["at"], json.dumps(r)))
    for h in load_holds().values():
        ix.q("INSERT OR REPLACE INTO holds VALUES (?,?,?,?)", (h["job"], h["id"], h["ticket"], h["at"]))
    ix.q("INSERT OR REPLACE INTO metadata VALUES ('revision', ?)", (git_revision(),))
    ix.q("INSERT OR REPLACE INTO metadata VALUES ('updated', ?)", (now(),))
    ix.close()
    stats["revision"] = git_revision()
    stats["index"] = INDEX.relative_to(ROOT).as_posix()
    return stats


def index_check():
    """Is the index current? Compares shard fingerprints and the git revision; opens no bodies."""
    if not INDEX.exists():
        return {"current": False, "why": "no index"}
    ix = Index(readonly=True)
    indexed = dict(ix.q("SELECT path, sha256 FROM shards").fetchall())
    rev = ix.meta("revision")
    ix.close()
    present = {}
    for d in domain_dirs():
        for shard in d.glob("artifacts-*.jsonl"):
            present[shard.relative_to(ROOT).as_posix()] = file_sha(shard)
    stale = [p for p in set(present) | set(indexed) if present.get(p) != indexed.get(p)]
    return {"current": not stale and rev == git_revision(), "stale_shards": sorted(stale),
            "indexed_revision": rev, "current_revision": git_revision()}


def ensure_index():
    if not index_check()["current"]:
        update_index()


def refresh_views(quiet=False):
    update_index()
    recs = load_records()
    for d in domain_dirs():
        write_domain_view(d.name, recs)


def write_domain_view(domain, recs):
    """ledger/<domain>/index.md: generated navigation between markers; authored text outside kept."""
    p = LEDGER / domain / "index.md"
    rows = sorted((r for r in recs.values() if r["domain"] == domain), key=lambda r: (r["kind"], r.get("path") or ""))
    lines = ["<!-- ledger:generated -->", f"Generated from the ledger records on {now()}. Do not edit inside the markers.", ""]
    lines += ["| id | kind | state | path | purpose | topics |", "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | {r['kind']} | {r['state']} | `{r.get('path')}` | {r.get('purpose','')} | {', '.join(r.get('topics', []))} |")
    lines.append("<!-- /ledger:generated -->")
    block = "\n".join(lines)
    if p.exists():
        text = p.read_text(encoding="utf-8")
        if "<!-- ledger:generated -->" in text and "<!-- /ledger:generated -->" in text:
            head, rest = text.split("<!-- ledger:generated -->", 1)
            _, tail = rest.split("<!-- /ledger:generated -->", 1)
            text = head + block + tail
        else:
            text = text.rstrip("\n") + "\n\n" + block + "\n"
    else:
        text = f"# Domain ledger: {domain}\n\nAuthored notes may go above or below the generated block.\n\n{block}\n"
    tmp = p.with_name(p.name + ".tmp-" + uuid.uuid4().hex[:8])
    tmp.write_text(text, encoding="utf-8"); tmp.replace(p)


# ---------------------------------------------------------------- queries (index first)
def with_measures(payload):
    payload["measures"] = dict(MEASURES)
    return payload


def cmd_show(args):
    ensure_index()
    ix = Index(readonly=True)
    if args.id:
        row = ix.q("SELECT json FROM artifacts WHERE id=?", (args.id,)).fetchone()
    else:
        row = ix.q("SELECT json FROM artifacts WHERE path=? AND state!='retired'", (args.path,)).fetchone()
    if not row:
        ix.close(); fail("not registered")
    r = json.loads(row[0])
    r["required_by"] = required_by_index(ix, r["id"])
    ix.close()
    emit(with_measures(r))


def required_by_index(ix, aid, direct=False):
    """Every edge (consumer requires X) reachable upward from aid; a consumer is expanded once."""
    seen, queue, out = {aid}, [aid], []
    while queue:
        cur = queue.pop(0)
        for (c,) in ix.q("SELECT consumer FROM inputs WHERE input=?", (cur,)).fetchall():
            st = ix.q("SELECT domain, path, state FROM artifacts WHERE id=?", (c,)).fetchone()
            out.append({"id": c, "domain": st[0], "path": st[1], "state": st[2], "requires": cur})
            if c not in seen:
                seen.add(c)
                if not direct:
                    queue.append(c)
    return out


def cmd_find(args):
    ensure_index()
    ix = Index(readonly=True)
    sql, params = "SELECT a.json FROM artifacts a", []
    where = []
    if args.topic:
        sql += " JOIN topics t ON t.id=a.id"; where.append("t.topic=?"); params.append(args.topic)
    if args.text:
        where.append("(a.purpose LIKE ? OR a.path LIKE ?)"); params += [f"%{args.text}%", f"%{args.text}%"]
    for f in ("ticket", "domain", "kind", "state"):
        v = getattr(args, f)
        if v:
            where.append(f"a.{f}=?"); params.append(v)
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = [json.loads(r[0]) for r in ix.q(sql + " ORDER BY a.domain, a.path", params).fetchall()]
    ix.close()
    emit(with_measures({"count": len(rows), "items": [{k: r.get(k) for k in ("id", "domain", "path", "kind", "state",
                                                                           "version", "purpose", "topics")} for r in rows]}))


def cmd_requires(args):
    ensure_index()
    ix = Index(readonly=True)
    row = ix.q("SELECT json FROM artifacts WHERE id=?", (args.id,)).fetchone()
    if not row:
        ix.close(); fail("not registered")
    r = json.loads(row[0])
    out = []
    for i in r.get("inputs", []):
        st = ix.q("SELECT domain, path, state, digest FROM artifacts WHERE id=?", (i["id"],)).fetchone()
        out.append({"id": i["id"], "pinned": i.get("digest"), "domain": st[0] if st else None,
                    "path": st[1] if st else None, "state": st[2] if st else ("library" if i["id"].startswith("sha256-") else "unregistered"),
                    "current_digest": st[3] if st else None})
    ix.close()
    emit(with_measures({"id": args.id, "requires": out}))


def cmd_required_by(args):
    ensure_index()
    ix = Index(readonly=True)
    out = required_by_index(ix, args.id, direct=args.direct)
    ix.close()
    emit(with_measures({"id": args.id, "required_by": out, "transitive": not args.direct}))


# ---------------------------------------------------------------- holds
def cmd_hold(args):
    recs = load_records()
    if args.id not in recs:
        fail("unknown artifact")
    HOLDS.mkdir(parents=True, exist_ok=True)
    write_atomic(HOLDS / f"{safe(args.job)}.json", {"job": args.job, "id": args.id, "ticket": args.ticket,
                                                     "at": now(), "version": recs[args.id]["version"]})
    update_index()
    emit({"held": args.id, "job": args.job})


def cmd_release(args):
    p = HOLDS / f"{safe(args.job)}.json"
    if p.exists():
        p.unlink()
    update_index()
    emit({"released": args.job})


# ---------------------------------------------------------------- drift
def domain_roots(domain):
    p = LEDGER / domain / "domain.json"
    if p.is_file():
        return read_json_file(p).get("roots", [])
    return []


def walk_files(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            if not fn.startswith(".tmp-"):
                yield Path(dp) / fn


def unregistered_under(recs, domain):
    known = {r["path"] for r in recs.values() if r["state"] != "retired"}
    n = b = 0
    for root in domain_roots(domain):
        base = ROOT / root
        if not base.exists():
            continue
        for f in walk_files(base):
            rp = rel(f)
            if rp not in known:
                n += 1; b += f.stat().st_size
    return {"files": n, "bytes": b}


def drift_report(domain=None, verify=True):
    recs = load_records()
    out, uncommitted = [], []
    status = {}
    if git_revision() != "nogit":
        txt = git("status", "--porcelain", "--untracked-files=all", "--", *domain_roots(domain)) if domain else \
            git("status", "--porcelain", "--untracked-files=all")
        for line in (txt or "").splitlines():
            status[line[3:].strip().strip('"')] = line[:2].strip()
    for r in recs.values():
        if domain and r["domain"] != domain:
            continue
        if r["state"] == "retired":
            if r.get("path") and (ROOT / r["path"]).exists() and not path_owner(recs, r["path"]):
                out.append({"id": r["id"], "path": r["path"], "drift": "retired artifact's path exists again, unregistered"})
            continue
        p = ROOT / r["path"]
        if not p.is_file():
            out.append({"id": r["id"], "path": r["path"], "drift": "missing from disk"}); continue
        if p.stat().st_size != r.get("bytes"):
            out.append({"id": r["id"], "path": r["path"], "drift": "size and digest differ from record (external edit)",
                        "git": status.get(r["path"])}); continue
        if verify and digest_file(p) != r["digest"]:
            out.append({"id": r["id"], "path": r["path"], "drift": "digest differs from record (external edit, same size)",
                        "git": status.get(r["path"])}); continue
        if r["path"] in status:                 # record and disk agree; git has not got the bytes yet
            uncommitted.append({"id": r["id"], "path": r["path"], "git": status[r["path"]],
                                "note": "accepted by the ledger, not committed" if status[r["path"]] != "??" else "accepted by the ledger, untracked"})
    result = {"drift": out, "uncommitted": uncommitted,
              "checked": sum(1 for r in recs.values() if (not domain or r["domain"] == domain) and r["state"] != "retired")}
    if domain:
        result["unregistered"] = unregistered_under(recs, domain)
    return result


def cmd_drift(args):
    emit(with_measures(drift_report(args.domain)))


# ---------------------------------------------------------------- recover
def cmd_recover(args):
    acts = []
    with Lock():
        if PENDING.is_dir():
            for p in sorted(PENDING.glob("*.json")):
                if p.name.startswith("spec-"):
                    p.unlink(); acts.append({"pending": p.name, "action": "removed stale archive spec"}); continue
                staged = read_json_file(p)
                key = staged["op_key"]
                if receipt_path(key).is_file():
                    p.unlink(); acts.append({"op_key": key, "action": "accepted before the interruption; views replayed"})
                    continue
                recs = load_records()
                partial = any(r.get("changed", {}).get("op_key") == key for r in recs.values())
                if partial:
                    receipt = integrate(staged)
                    write_atomic(receipt_path(key), receipt)
                    p.unlink(); acts.append({"op_key": key, "action": "partially applied; finished and receipted"})
                else:
                    p.unlink(); acts.append({"op_key": key, "action": "staged only; discarded (retry the batch)"})
        refresh_views()
    emit({"actions": acts, "index": index_check()})


# ---------------------------------------------------------------- Housekeeper
def disposition(recs, r, holds, verify=True):
    """eligible / held (named consumer or policy) / unresolved (never permission)."""
    reasons, state = [], "eligible"
    def hold(why): nonlocal state; state = "held"; reasons.append(why)
    def unres(why):
        nonlocal state
        if state != "held": state = "unresolved"
        reasons.append(why)
    if r["state"] == "retired":
        return "skip", ["already retired"]
    if (p := is_protected(r.get("path") or "")):
        hold(f"policy: protected root {p}")
    if r.get("policy") in ("retain", "approved-edition"):
        hold(f"policy: {r['policy']}")
    for h in holds.values():
        if h["id"] == r["id"]:
            hold(f"job hold: {h['job']} (ticket {h['ticket']})")
    for e in chain_records(recs, r["id"]):
        if e["consumer_state"] != "retired":
            c = recs[e["consumer"]]
            hold(f"required by {c['id']} ({c['domain']}: {c['path']}) via {e['requires']}" if e["requires"] != r["id"]
                 else f"required by {c['id']} ({c['domain']}: {c['path']})")
    p = ROOT / r["path"]
    if not p.is_file():
        unres("missing from disk: register --reconcile or restore first")
    else:
        if p.stat().st_nlink > 1:
            unres(f"shares storage with {p.stat().st_nlink - 1} other path(s): determine which one the consumer requires")
        if verify and digest_file(p) != r["digest"]:
            unres("drift: disk bytes differ from the record")
    if r.get("coverage") != "reconciled":
        unres("consumers not reconciled: an empty reverse lookup is not permission")
    if r["state"] == "inventoried" or r.get("purpose") in (None, "unknown"):
        unres("purpose unknown (inventoried, not enriched)")
    dangling = [s["id"] for s in recs.values() if r["id"] in s.get("links", []) and s["state"] != "retired"]
    return state, reasons + ([f"navigation link from {', '.join(dangling)} will dangle (separate disposition: repoint or accept)"] if dangling and state == "eligible" else [])


def cmd_housekeep_plan(args):
    ensure_index()
    ix = Index(readonly=True)
    sql, params, where = "SELECT a.id FROM artifacts a", [], ["a.state!='retired'"]
    if args.topic:
        sql += " JOIN topics t ON t.id=a.id"; where.append("t.topic=?"); params.append(args.topic)
    for f in ("domain", "kind", "state"):
        if getattr(args, f):
            where.append(f"a.{f}=?"); params.append(getattr(args, f))
    if args.expired:
        where.append("a.expires IS NOT NULL AND a.expires < ?"); params.append(today())
    ids = [row[0] for row in ix.q(sql + " WHERE " + " AND ".join(where), params).fetchall()]
    indexed_count = ix.q("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    ix.close()
    recs = load_records()                       # dispositions read the authoritative records
    holds = load_holds()
    items, groups = [], {"eligible": 0, "held": 0, "unresolved": 0}
    for aid in ids:
        r = recs.get(aid)
        if not r or any(glob_match(x, r["path"]) for x in (args.exclude or [])):
            continue
        st, why = disposition(recs, r, holds)
        if st == "skip":
            continue
        groups[st] += 1
        items.append({"id": aid, "version": r["version"], "digest": r["digest"], "path": r["path"], "domain": r["domain"],
                      "kind": r["kind"], "bytes": r["bytes"], "disposition": st, "reasons": why})
    cost = {}
    for d in sorted({i["domain"] for i in items} | ({args.domain} if args.domain else set())):
        cost[d] = unregistered_under(recs, d)
    plan = {"plan": "P-" + uuid.uuid4().hex[:8], "request": args.request, "at": now(), "revision": git_revision(),
            "filter": {k: getattr(args, k) for k in ("domain", "topic", "kind", "state", "expired", "exclude")},
            "index_size": indexed_count, "items": items, "groups": groups,
            "reconciliation_cost": {"unregistered_files_under_domain_roots": cost,
                                    "note": "unresolved items need these files inventoried or the named consumer checked before they can become eligible"},
            "approved": None}
    if indexed_count == 0:
        plan["warning"] = "empty index: nothing can be approved from it"
    PLANS.mkdir(parents=True, exist_ok=True)
    write_atomic(PLANS / f"{plan['plan']}.json", plan)
    emit(with_measures(plan))


def cmd_housekeep_approve(args):
    p = PLANS / f"{args.plan}.json"
    if not p.is_file():
        fail("unknown plan")
    plan = read_json_file(p)
    want = set(args.ids.split(","))
    bound = []
    for it in plan["items"]:
        if it["id"] in want:
            if it["disposition"] != "eligible":
                fail(f"{it['id']} is {it['disposition']}, not eligible: {it['reasons']}")
            bound.append({"id": it["id"], "version": it["version"], "digest": it["digest"], "path": it["path"]})
    missing = want - {b["id"] for b in bound}
    if missing:
        fail(f"not in the plan: {sorted(missing)}")
    plan["approved"] = {"by": args.by, "at": now(), "items": bound, "scope": plan["filter"]}
    write_atomic(p, plan)
    emit({"plan": args.plan, "approved": plan["approved"]})


def cmd_housekeep_apply(args):
    p = PLANS / f"{args.plan}.json"
    if not p.is_file():
        fail("unknown plan")
    plan = read_json_file(p)
    if not plan.get("approved"):
        fail("plan is not approved")
    rp = receipt_path(args.op_key)
    if rp.is_file():
        r = read_json_file(rp); r["already"] = "accepted"; emit(r); return
    with Lock():
        recs = load_records(); holds = load_holds()
        ops, outcome = [], {"retired": [], "held": [], "changed": [], "unresolved": []}
        for b in plan["approved"]["items"]:
            r = recs.get(b["id"])
            if not r or r["version"] != b["version"] or r["digest"] != b["digest"] or r["path"] != b["path"]:
                outcome["changed"].append({"id": b["id"], "planned": b, "now": {k: r.get(k) for k in ("version", "digest", "path", "state")} if r else None,
                                           "why": "changed since the plan; needs a fresh disposition"})
                continue
            st, why = disposition(recs, r, holds)       # revalidated now, including new consumers and holds
            if st != "eligible":
                outcome["held" if st == "held" else "unresolved"].append({"id": r["id"], "reasons": why})
                continue
            ops.append({"op": "retire", "id": r["id"], "expected_version": r["version"], "reason": plan["request"],
                        "approval": plan["plan"]})
        receipt = {"receipt": args.op_key, "ticket": args.ticket, "attempt_id": args.attempt_id, "role": "vault-cleanup",
                   "at": now(), "plan": plan["plan"], "revision_before": git_revision(), "results": [], "declared_ops": len(ops)}
        if ops:
            staged = stage({"op_key": args.op_key, "ticket": args.ticket, "attempt_id": args.attempt_id,
                            "role": "vault-cleanup", "ops": ops})
            inner = integrate(staged)
            receipt["results"] = inner["results"]
            (PENDING / f"{safe(args.op_key)}.json").unlink(missing_ok=True)
        for res in receipt["results"]:
            if res["op"] == "retire":
                outcome["retired"].append({"id": res["id"], "path": res["path"], "logical_bytes": res["logical_bytes"],
                                           "physical_bytes_freed": res["physical_bytes_freed"], "backup": res["backup"]["zip"]})
        receipt["outcome"] = outcome
        receipt["savings"] = {"removed_paths": len(outcome["retired"]),
                              "logical_bytes": sum(x["logical_bytes"] for x in outcome["retired"]),
                              "physical_bytes_freed_measured": sum(x["physical_bytes_freed"] for x in outcome["retired"])}
        write_atomic(rp, receipt)
        try:
            refresh_views()
        except Exception as e:
            receipt["views"] = f"stale: {e}"
    emit(with_measures(receipt))


# ---------------------------------------------------------------- inventory (bootstrap, cheap)
def guess_kind(path):
    p = path.lower()
    if "/pages/" in p and p.endswith((".html", ".htm")):
        return "report-source"
    if p.endswith((".py", ".cjs", ".js", ".ps1")):
        return "build-code"
    if p.endswith((".csv", ".tsv", ".xlsx", ".parquet", ".jsonl")) and "/research/" in p:
        return "dataset"
    if p.endswith((".png", ".svg", ".jpg", ".webp")):
        return "figure"
    if p.endswith("findings.md") or p.endswith("manifest.md"):
        return "findings"
    return "unknown"


QUOTED = re.compile(r"""["']([^"'\n]{1,160}\.(?:csv|tsv|xlsx|json|svg|png|html|md|py|pdf))["']""")
IMPORT = re.compile(r"^\s*import\s+([A-Za-z_][A-Za-z0-9_]*)|^\s*from\s+([A-Za-z_][A-Za-z0-9_]*)\s+import", re.M)
FOLDER = re.compile(r"""["']((?:[A-Za-z0-9_-]+/)*(?:pages|research|graphs)[A-Za-z0-9_/-]*)["']""")
TOKEN = re.compile(r"""["']([A-Za-z0-9_-]{2,60})["']""")


def infer_inputs(files):
    """Mechanical import of what build code names: quoted file names that resolve to an inventoried
    file by basename (unique), sibling modules it imports, and the pages folder it writes into.
    Marked basis=inferred-from-script; coverage stays unverified until a person confirms."""
    by_base = {}
    for f in files:
        by_base.setdefault(Path(f).name, []).append(f)
    inputs = {f: set() for f in files}
    outside = {}
    for f in files:
        if guess_kind(f) != "build-code":
            continue
        body = (ROOT / f).read_text(encoding="utf-8", errors="replace")
        MEASURES["file_bodies_opened"] += 1; MEASURES["bytes_read"] += len(body.encode("utf-8"))
        for m in QUOTED.finditer(body):
            base = Path(m.group(1)).name
            hits = by_base.get(base, [])
            if len(hits) == 1 and hits[0] != f:
                if guess_kind(hits[0]) in ("report-source", "figure"):
                    inputs[hits[0]].add(f)            # a page or figure a script names is what it writes
                else:
                    inputs[f].add(hits[0])            # data or code a script names is what it reads
            elif not hits and not m.group(1).endswith((".html", ".svg", ".png", ".md")):
                outside.setdefault(f, []).append(m.group(1))
        for a, b in IMPORT.findall(body):
            mod = a or b
            sib = str(Path(f).parent / f"{mod}.py").replace("\\", "/")
            if sib in inputs and sib != f:
                inputs[f].add(sib)
        # the pages the script writes: a quoted path containing pages/<scope>, or os.path.join
        # style tokens "pages", "<scope>" both quoted somewhere in the script
        tokens = set(TOKEN.findall(body))
        scopes = set()
        for m in FOLDER.finditer(body):
            parts = m.group(1).strip("/").split("/")
            if "pages" in parts and len(parts) > parts.index("pages") + 1:
                scopes.add(parts[parts.index("pages") + 1])
        for g in files:
            parts = g.split("/")
            if guess_kind(g) == "report-source" and "pages" in parts:
                scope = parts[parts.index("pages") + 1] if len(parts) > parts.index("pages") + 1 else None
                if scope and (scope in scopes or ("pages" in tokens and scope in tokens)):
                    inputs[g].add(f)
    # transitive data inputs of a page: through its build code and the modules the code imports
    changed = True
    while changed:
        changed = False
        for g in files:
            if guess_kind(g) != "report-source":
                continue
            for code in list(inputs[g]):
                for x in inputs.get(code, ()):
                    if guess_kind(x) in ("dataset", "build-code") and x not in inputs[g]:
                        inputs[g].add(x); changed = True
    return inputs, outside


def cmd_inventory(args):
    files = []
    for root in args.roots:
        base = local_path(root)
        if base.is_file():
            files.append(rel(base))
        else:
            files += [rel(f) for f in walk_files(base)]
    files = sorted(set(files))
    tracked = set((git("ls-files", "--", *args.roots) or "").splitlines())
    inputs, outside = infer_inputs(files) if args.infer_inputs else ({f: set() for f in files}, {})
    op_key = args.op_key or f"inventory-{args.domain}-{today()}"
    ids = {f: new_id(op_key, i) for i, f in enumerate(files)}
    recs = []
    for f in files:
        st = (ROOT / f).stat()
        recs.append({"id": ids[f], "domain": args.domain, "path": f, "kind": guess_kind(f), "bytes": st.st_size,
                     "nlink": st.st_nlink, "git": "tracked" if f in tracked else "untracked",
                     "topics": args.topics or [], "state": "inventoried", "coverage": "unverified", "purpose": "unknown",
                     "inputs": sorted(ids[x] for x in inputs[f]), "input_paths": sorted(inputs[f]),
                     "inputs_outside_roots": outside.get(f, [])})
    out = {"domain": args.domain, "roots": args.roots, "revision": git_revision(), "files": len(files),
           "bytes": sum(r["bytes"] for r in recs), "written": False, "records": recs,
           "gaps": [{"build_code": k, "names_inputs_not_in_roots": v} for k, v in outside.items()],
           "cost_class": "bootstrap (one-time); steady state reads no bodies"}
    if args.chain:
        target = ids.get(args.chain) or fail(f"{args.chain} is not under the roots")
        fake = {r["id"]: dict(r, state="inventoried", inputs=[{"id": i} for i in r["inputs"]]) for r in recs}
        up, seen, queue = [], set(), [target]
        while queue:                                   # what the target requires, transitively
            cur = queue.pop(0)
            for i in fake[cur]["inputs"]:
                up.append({"consumer": fake[cur]["path"], "requires": fake[i["id"]]["path"], "kind": fake[i["id"]]["kind"]})
                if i["id"] not in seen:
                    seen.add(i["id"]); queue.append(i["id"])
        out["chain"] = {"target": args.chain, "requires": up, "required_by": chain_records(fake, target)}
    if args.write:
        batch = {"op_key": op_key, "ticket": args.ticket or "inventory", "role": None,
                 "ops": [{"op": "register", "id": r["id"], "domain": args.domain, "path": r["path"], "kind": r["kind"],
                          "topics": r["topics"], "basis": "mechanical inventory" + (" + inferred-from-script" if r["inputs"] else "")}
                         for r in recs]}
        # a second pass declares inputs once every id exists
        receipt = apply_batch(batch)
        if not receipt.get("already"):
            all_recs = load_records()
            touched = set()
            for r in recs:
                if r["inputs"] and r["id"] in all_recs:
                    all_recs[r["id"]]["inputs"] = [{"id": i, "digest": None, "basis": "inferred-from-script"} for i in r["inputs"]]
                    touched.add((args.domain, r["id"]))
            save_records(all_recs, touched)
            (LEDGER / args.domain).mkdir(parents=True, exist_ok=True)
            write_atomic(LEDGER / args.domain / "domain.json",
                         {"domain": args.domain, "roots": args.roots, "inventoried_at": git_revision(), "on": now(),
                          "consumer_classes": {"build code under the roots": "inventoried, inputs inferred from script text",
                                               "pages outside the roots": "unverified", "notes and ROADMAP links": "unverified"}})
            refresh_views()
        out["written"] = True; out["receipt"] = receipt["receipt"]
    emit(with_measures(out))


# ---------------------------------------------------------------- CLI
def parse_inputs(s):
    if not s:
        return []
    out = []
    for part in s.split(","):
        aid, _, dig = part.partition("@")
        out.append({"id": aid, "digest": dig or None})
    return out


def one_op_batch(args, op):
    batch = {"op_key": args.op_key, "ticket": args.ticket, "attempt_id": getattr(args, "attempt_id", None),
             "role": getattr(args, "role", None), "run": getattr(args, "run", None), "ops": [op]}
    emit(apply_batch(batch))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, expected=False):
        p.add_argument("--op-key", dest="op_key", required=True); p.add_argument("--ticket", required=True)
        p.add_argument("--attempt-id", dest="attempt_id"); p.add_argument("--role"); p.add_argument("--run")
        if expected:
            p.add_argument("--id", required=True); p.add_argument("--expected-version", dest="expected_version", type=int)

    b = sub.add_parser("batch"); b.add_argument("--file", required=True)
    b.set_defaults(func=lambda a: emit(apply_batch(read_json_file(a.file))))

    c = sub.add_parser("create"); common(c)
    for f in ("--domain", "--path"):
        c.add_argument(f, required=True)
    c.add_argument("--source"); c.add_argument("--kind", default="unknown"); c.add_argument("--purpose")
    c.add_argument("--topics"); c.add_argument("--inputs"); c.add_argument("--links"); c.add_argument("--policy", default="default")
    c.add_argument("--coverage", default="reconciled"); c.add_argument("--expires")
    c.set_defaults(func=lambda a: one_op_batch(a, {"op": "create", "domain": a.domain, "path": a.path, "source": a.source,
        "kind": a.kind, "purpose": a.purpose, "topics": (a.topics or "").split(",") if a.topics else [],
        "inputs": parse_inputs(a.inputs), "links": (a.links or "").split(",") if a.links else [], "policy": a.policy,
        "coverage": a.coverage, "expires": a.expires}))

    m = sub.add_parser("modify"); common(m, expected=True)
    m.add_argument("--source"); m.add_argument("--purpose"); m.add_argument("--kind"); m.add_argument("--topics")
    m.add_argument("--inputs"); m.add_argument("--links"); m.add_argument("--policy"); m.add_argument("--coverage"); m.add_argument("--expires")
    m.set_defaults(func=lambda a: one_op_batch(a, {k: v for k, v in {"op": "modify", "id": a.id, "expected_version": a.expected_version,
        "source": a.source, "purpose": a.purpose, "kind": a.kind, "topics": a.topics.split(",") if a.topics else None,
        "inputs": parse_inputs(a.inputs) if a.inputs is not None else None, "links": a.links.split(",") if a.links else None,
        "policy": a.policy, "coverage": a.coverage, "expires": a.expires}.items() if v is not None or k in ("op", "id", "expected_version")}))

    v = sub.add_parser("move"); common(v, expected=True); v.add_argument("--to", required=True); v.add_argument("--domain")
    v.set_defaults(func=lambda a: one_op_batch(a, {"op": "move", "id": a.id, "expected_version": a.expected_version, "to": a.to, "domain": a.domain}))

    t = sub.add_parser("retire"); common(t, expected=True); t.add_argument("--reason", required=True); t.add_argument("--approval")
    t.add_argument("--force", action="store_true", help="retire although consumers require it (recorded)")
    t.set_defaults(func=lambda a: one_op_batch(a, {"op": "retire", "id": a.id, "expected_version": a.expected_version, "reason": a.reason,
                                                   "approval": a.approval, "force": a.force}))

    s = sub.add_parser("restore"); common(s); s.add_argument("--id", required=True); s.add_argument("--to")
    s.set_defaults(func=lambda a: one_op_batch(a, {"op": "restore", "id": a.id, "to": a.to}))

    g = sub.add_parser("register"); common(g)
    for f in ("--domain", "--path"):
        g.add_argument(f, required=True)
    g.add_argument("--kind", default="unknown"); g.add_argument("--purpose"); g.add_argument("--topics"); g.add_argument("--inputs")
    g.add_argument("--coverage"); g.add_argument("--policy", default="default"); g.add_argument("--basis", default="mechanical inventory")
    g.add_argument("--reconcile", action="store_true", help="accept an external edit of an already registered path as a new version")
    g.set_defaults(func=lambda a: one_op_batch(a, {"op": "register", "domain": a.domain, "path": a.path, "kind": a.kind, "purpose": a.purpose,
        "topics": a.topics.split(",") if a.topics else [], "inputs": parse_inputs(a.inputs), "coverage": a.coverage or ("reconciled" if a.inputs is not None else "unverified"),
        "policy": a.policy, "basis": a.basis, "reconcile": a.reconcile}))

    sh = sub.add_parser("show"); sh.add_argument("--id"); sh.add_argument("--path"); sh.set_defaults(func=cmd_show)
    fd = sub.add_parser("find")
    for f in ("--topic", "--text", "--ticket", "--domain", "--kind", "--state"):
        fd.add_argument(f)
    fd.set_defaults(func=cmd_find)
    rq = sub.add_parser("requires"); rq.add_argument("--id", required=True); rq.set_defaults(func=cmd_requires)
    rb = sub.add_parser("required-by"); rb.add_argument("--id", required=True); rb.add_argument("--direct", action="store_true")
    rb.set_defaults(func=cmd_required_by)
    h = sub.add_parser("hold"); h.add_argument("--id", required=True); h.add_argument("--job", required=True); h.add_argument("--ticket", required=True)
    h.set_defaults(func=cmd_hold)
    rl = sub.add_parser("release"); rl.add_argument("--job", required=True); rl.set_defaults(func=cmd_release)
    d = sub.add_parser("drift"); d.add_argument("--domain"); d.set_defaults(func=cmd_drift)
    ix = sub.add_parser("index"); ix.add_argument("--rebuild", action="store_true"); ix.add_argument("--check", action="store_true")
    ix.set_defaults(func=lambda a: emit(index_check() if a.check else update_index(rebuild=a.rebuild)))
    rc = sub.add_parser("recover"); rc.set_defaults(func=cmd_recover)

    hk = sub.add_parser("housekeep"); hks = hk.add_subparsers(dest="hcmd", required=True)
    pl = hks.add_parser("plan"); pl.add_argument("--request", required=True)
    for f in ("--domain", "--topic", "--kind", "--state"):
        pl.add_argument(f)
    pl.add_argument("--expired", action="store_true"); pl.add_argument("--exclude", action="append")
    pl.set_defaults(func=cmd_housekeep_plan)
    apv = hks.add_parser("approve"); apv.add_argument("--plan", required=True); apv.add_argument("--ids", required=True); apv.add_argument("--by", required=True)
    apv.set_defaults(func=cmd_housekeep_approve)
    apl = hks.add_parser("apply"); apl.add_argument("--plan", required=True); apl.add_argument("--op-key", dest="op_key", required=True)
    apl.add_argument("--ticket", required=True); apl.add_argument("--attempt-id", dest="attempt_id")
    apl.set_defaults(func=cmd_housekeep_apply)

    inv = sub.add_parser("inventory"); inv.add_argument("--domain", required=True); inv.add_argument("--roots", nargs="+", required=True)
    inv.add_argument("--topics", nargs="*"); inv.add_argument("--infer-inputs", dest="infer_inputs", action="store_true")
    inv.add_argument("--write", action="store_true"); inv.add_argument("--chain"); inv.add_argument("--op-key", dest="op_key"); inv.add_argument("--ticket")
    inv.set_defaults(func=cmd_inventory)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
