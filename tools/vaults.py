"""Domain repositories as explicit external inputs.

superRepo is the agent layer; it owns no domain content. A vault (a domain repository such as a
research vault with field folders, topics, claim maps and pages) is registered in
config/vaults.json with its local path. Nothing here assumes a vault exists: a missing vault is
reported, never guessed.

  python tools/vaults.py list          every registered vault and whether its path exists here
  python tools/vaults.py check         exit 1 if a vault marked required is missing
  python tools/vaults.py resolve REF   where a reference such as topics/x/index.md resolves

Resolution order for a reference: this repository's root first (LIVEOS_ROOT), then each
registered vault in order. The environment variable LIVEOS_VAULTS can name another config file,
and LIVEOS_VAULT_<NAME> can override one vault's path for a session or a test.
"""
from pathlib import Path
import argparse, json, os, sys

ROOT = Path(os.environ.get("LIVEOS_ROOT") or Path(__file__).resolve().parents[1]).resolve()
CONFIG = Path(os.environ.get("LIVEOS_VAULTS") or (ROOT / "config" / "vaults.json"))


def load():
    if not CONFIG.is_file():
        return {"schema_version": 1, "vaults": {}}
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def vaults():
    """Ordered list of (name, spec, path or None)."""
    out = []
    for name, spec in load().get("vaults", {}).items():
        override = os.environ.get(f"LIVEOS_VAULT_{name.upper().replace('-', '_')}")
        raw = override or spec.get("path")
        path = Path(raw).expanduser() if raw else None
        out.append((name, spec, path if path and path.is_dir() else None))
    return out


def resolve(ref):
    """Path for a repository-relative reference, or None. Root first, then vaults in order."""
    if not ref:
        return None
    p = Path(ref)
    if p.is_absolute():
        return p if p.exists() else None
    if (ROOT / ref).exists():
        return ROOT / ref
    for _, _, path in vaults():
        if path and (path / ref).exists():
            return path / ref
    return None


def owner(path):
    """Which root (this repository or a vault name) a path lies under, or None."""
    path = Path(path).resolve()
    if path == ROOT or ROOT in path.parents:
        return "superrepo"
    for name, _, vp in vaults():
        if vp:
            vp = vp.resolve()
            if path == vp or vp in path.parents:
                return name
    return None


def where_to_look(ref):
    """Plain words for an error message: the places a reference was looked for."""
    places = [str(ROOT / ref)]
    for name, spec, path in vaults():
        places.append(f"{path / ref}" if path else f"<vault {name}: path {spec.get('path')!r} not present on this machine>")
    return places


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list"); sub.add_parser("check")
    r = sub.add_parser("resolve"); r.add_argument("ref")
    a = ap.parse_args()
    if a.cmd == "list":
        rows = [{"name": n, "path": s.get("path"), "present": p is not None, "required": bool(s.get("required")),
                 "role": s.get("role"), "note": s.get("note")} for n, s, p in vaults()]
        print(json.dumps({"config": str(CONFIG), "root": str(ROOT), "vaults": rows}, ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "check":
        missing = [n for n, s, p in vaults() if s.get("required") and p is None]
        print(json.dumps({"missing_required": missing, "present": [n for n, _, p in vaults() if p]}))
        return 1 if missing else 0
    p = resolve(a.ref)
    print(json.dumps({"ref": a.ref, "path": str(p) if p else None, "owner": owner(p) if p else None,
                      "looked_in": where_to_look(a.ref)}, ensure_ascii=False, indent=1))
    return 0 if p else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
