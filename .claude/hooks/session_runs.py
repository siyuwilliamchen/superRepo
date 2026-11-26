"""SessionStart hook: tell a new session what happened while nobody was looking.

Two ledgers on disk are read, so nothing depends on the session that started the work:

- tools/run.py        shell jobs: interrupted by a session ending, stalled, or failed
- tools/coordinator.py  the workflow queue: stalled or failed tickets, results waiting in a
                      session inbox, and whether the minute-check service is running

Reading the workflow ledger also runs one reconcile, so every session start is itself a
recovery tick: a dead worker is requeued even if the service was down.

Prints nothing when there is nothing to act on, so a normal session is not cluttered.
Never blocks a session: any failure here exits quietly.
"""
import json, os, subprocess, sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

try:
    json.load(sys.stdin)  # consume the event payload; nothing in it is needed
except Exception:
    pass


def tool(name, *args):
    try:
        out = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", name), *args],
                             cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20)
        return json.loads(out.stdout) if out.stdout.strip() else None
    except Exception:
        return None


lines = []

runs = tool("run.py", "status", "--json") or []
bad_runs = [r for r in runs if r.get("status") in ("interrupted", "stalled", "failed")]
if bad_runs:
    lines += ["Background jobs that did not finish cleanly. Read the log before re-running: "
              "a job may have done its work and only lost its result line."]
    for r in bad_runs:
        lines.append(f"- {r['status'].upper()} {r['id']}" + (f": {r['note']}" if r.get("note") else ""))
        lines.append(f"  log: {r.get('log')}")
        if r.get("resume"):
            lines.append(f"  resume: {r['resume']}")
        if r.get("exit_code") is not None:
            lines.append(f"  exit code: {r['exit_code']}")
    lines += ["  (`python tools/run.py status`, `python tools/run.py log <id>`)", ""]

h = tool("coordinator.py", "health") or {}
if h.get("just_reconciled"):
    lines.append("Workflow queue, recovered just now at session start:")
    for a in h["just_reconciled"]:
        lines.append("- " + " ".join(f"{k}={v}" for k, v in a.items()))
    lines.append("")
if h.get("problems"):
    lines.append("Workflow tickets that need attention:")
    for p in h["problems"]:
        detail = (f"no progress for {p['idle_seconds'] // 60} min, last milestone: {p.get('milestone')}"
                  if p["state"] == "stalled" else p.get("why"))
        lines.append(f"- {p['state'].upper()} {p['id']} ({p['kind']}): {p.get('question')}")
        lines.append(f"  {detail}")
    lines += ["  (`python tools/coordinator.py show <id>`)", ""]
if h.get("unread_results"):
    lines.append("Results waiting for William, not yet raised in conversation:")
    for session, n in h["unread_results"].items():
        lines.append(f"- session {session}: {n} (`python tools/coordinator.py inbox {session}`)")
    lines.append("")
if h.get("open_tickets") and h.get("service") != "running":
    lines += [f"The coordinator's minute check is {h.get('service')} with {h['open_tickets']} open "
              f"ticket(s). Start it: python tools/run.py start coordinator -- "
              f"python tools/coordinator.py serve", ""]

if lines:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": "\n".join(lines).strip()[:9000]}}))
