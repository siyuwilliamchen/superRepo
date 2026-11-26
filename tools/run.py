"""Run a long job so its state survives the session that started it.

Replaces the watchdog. A watchdog lives inside the session, so it dies with the session
and cannot tell "finished" from "killed". Here the record lives on disk:

  python tools/run.py start <name> -- <command ...>   run it, recording progress
  python tools/run.py status [--json] [--all]         what is running, done, stalled, interrupted
  python tools/run.py log <id> [--tail N]             the job's output
  python tools/run.py stop <id>                       stop a running job

How each failure is detected, without anything watching:
  finished      the record holds an exit code, written by the wrapper itself
  interrupted   state is "running" but the heartbeat is stale -> wrapper died (session ended,
                reboot, kill). Nothing is lost: re-run the resume command in the record.
  stalled       heartbeat fresh, child alive, but no CPU progress and no new output for
                --stall-after seconds -> the job is wedged, not working.

Records: .local/runs/<id>.json (machine state, git-ignored). Output: .local/runs/<id>.log
"""
from pathlib import Path
import argparse, datetime as dt, json, os, shlex, signal, subprocess, sys, threading, time

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / ".local" / "runs"
HEARTBEAT = 15          # seconds between heartbeats
STALE_AFTER = 90        # no heartbeat for this long while "running" -> interrupted
STALL_AFTER = 900       # no CPU progress and no output for this long -> stalled


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def cpu_seconds(pid):
    """Child CPU time, or None if it cannot be read on this platform."""
    try:
        import ctypes
        from ctypes import wintypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None
        try:
            creation = wintypes.FILETIME(); exit_ = wintypes.FILETIME()
            kernel = wintypes.FILETIME(); user = wintypes.FILETIME()
            ok = ctypes.windll.kernel32.GetProcessTimes(
                h, ctypes.byref(creation), ctypes.byref(exit_),
                ctypes.byref(kernel), ctypes.byref(user))
            if not ok:
                return None
            def to_s(ft):
                return ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7
            return round(to_s(kernel) + to_s(user), 2)
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        try:
            return round(sum(os.times()[:2]), 2)
        except Exception:
            return None


def alive(pid):
    if pid is None:
        return False
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    except Exception:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def write(record):
    RUNS.mkdir(parents=True, exist_ok=True)
    path = RUNS / f"{record['id']}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def start(name, command, resume, note):
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"{stamp}-{name}"
    RUNS.mkdir(parents=True, exist_ok=True)
    log = RUNS / f"{run_id}.log"
    rec = {"id": run_id, "name": name, "state": "running", "command": command,
           "resume": resume or f"python tools/run.py start {name} -- " + " ".join(shlex.quote(c) for c in command),
           "note": note, "cwd": str(ROOT), "log": str(log.relative_to(ROOT)),
           "started": now(), "heartbeat": now(), "pid": None, "child_pid": None,
           "cpu_seconds": None, "log_bytes": 0, "last_progress": now(),
           "exit_code": None, "finished": None}
    rec["pid"] = os.getpid()
    write(rec)
    print(f"run {run_id}")
    print(f"  record .local/runs/{run_id}.json")
    print(f"  log    .local/runs/{run_id}.log")

    try:
        return _supervise(rec, command, log)
    except BaseException as e:
        # The wrapper itself failed. Record that, so the run is never left saying "running".
        rec.update(state="failed", exit_code=None, finished=now(), heartbeat=now(),
                   error=f"{type(e).__name__}: {e}")
        write(rec)
        print(f"wrapper failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


def _supervise(rec, command, log):
    with log.open("wb") as out:
        proc = subprocess.Popen(command, cwd=str(ROOT), stdout=out,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        rec["child_pid"] = proc.pid
        write(rec)
        stop_beating = threading.Event()

        def beat():
            last_cpu, last_bytes = None, -1
            while not stop_beating.wait(HEARTBEAT):
                cpu = cpu_seconds(proc.pid)
                try:
                    size = log.stat().st_size
                except OSError:
                    size = rec["log_bytes"]
                moved = (cpu is not None and last_cpu is not None and cpu - last_cpu > 0.5) or size != last_bytes
                if moved or last_cpu is None:
                    rec["last_progress"] = now()
                last_cpu, last_bytes = cpu, size
                rec.update(heartbeat=now(), cpu_seconds=cpu, log_bytes=size)
                write(rec)

        t = threading.Thread(target=beat, daemon=True)
        t.start()
        try:
            code = proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            code = proc.wait()
        finally:
            stop_beating.set()
    try:
        rec["log_bytes"] = log.stat().st_size
    except OSError:
        pass
    rec.update(state="done" if code == 0 else "failed", exit_code=code,
               heartbeat=now(), finished=now(), cpu_seconds=cpu_seconds(proc.pid))
    write(rec)
    print(f"{rec['state']} (exit {code})")
    return code


def age(iso):
    try:
        return (dt.datetime.now().astimezone() - dt.datetime.fromisoformat(iso)).total_seconds()
    except Exception:
        return 1e9


def classify(rec, stall_after):
    if rec["state"] in ("done", "failed", "stopped"):
        return rec["state"]
    if age(rec.get("heartbeat", "")) > STALE_AFTER or not alive(rec.get("pid")):
        return "interrupted"
    if age(rec.get("last_progress", "")) > stall_after:
        return "stalled"
    return "running"


def human(seconds):
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}"


def status(as_json, show_all, stall_after):
    recs = []
    for p in sorted(RUNS.glob("*.json")):
        try:
            recs.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    for r in recs:
        r["status"] = classify(r, stall_after)
    live = [r for r in recs if r["status"] in ("running", "stalled", "interrupted")]
    shown = recs if show_all else (live or recs[-5:])
    if as_json:
        print(json.dumps(shown, indent=1))
        return 1 if any(r["status"] in ("stalled", "interrupted", "failed") for r in live) else 0
    if not recs:
        print("no runs recorded")
        return 0
    print(f"{'status':12s} {'age':>6s} {'idle':>6s}  id")
    for r in shown:
        print(f"{r['status']:12s} {human(age(r['started'])):>6s} "
              f"{human(age(r.get('last_progress', r['started']))):>6s}  {r['id']}")
    bad = [r for r in live if r["status"] in ("stalled", "interrupted")]
    for r in bad:
        print()
        if r["status"] == "interrupted":
            print(f"INTERRUPTED {r['id']}: the wrapper stopped without recording an exit code")
            print(f"  (session ended, reboot or kill). Last output {human(age(r['heartbeat']))} ago.")
        else:
            print(f"STALLED {r['id']}: alive but no CPU progress or output for "
                  f"{human(age(r['last_progress']))}.")
            print(f"  Inspect, then: python tools/run.py stop {r['id']}")
        print(f"  log:    .local/runs/{r['id']}.log")
        print(f"  resume: {r['resume']}")
        if r.get("note"):
            print(f"  note:   {r['note']}")
    return 1 if bad else 0


def log_cmd(run_id, tail):
    matches = sorted(RUNS.glob(f"*{run_id}*.log"))
    if not matches:
        raise SystemExit(f"no log for {run_id}")
    text = matches[-1].read_text(encoding="utf-8", errors="replace").splitlines()
    print("\n".join(text[-tail:]))


def stop_cmd(run_id):
    matches = sorted(RUNS.glob(f"*{run_id}*.json"))
    if not matches:
        raise SystemExit(f"no run {run_id}")
    rec = json.loads(matches[-1].read_text(encoding="utf-8"))
    for pid in (rec.get("child_pid"), rec.get("pid")):
        if pid and alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"stopped pid {pid}")
            except OSError as e:
                print(f"could not stop pid {pid}: {e}")
    rec.update(state="stopped", finished=now())
    write(rec)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("name")
    s.add_argument("--resume", help="command that continues this job after an interruption")
    s.add_argument("--note", help="one line: what this job is for")
    t = sub.add_parser("status")
    t.add_argument("--json", action="store_true")
    t.add_argument("--all", action="store_true")
    t.add_argument("--stall-after", type=int, default=STALL_AFTER)
    g = sub.add_parser("log"); g.add_argument("id"); g.add_argument("--tail", type=int, default=40)
    k = sub.add_parser("stop"); k.add_argument("id")
    # Split the job's command off at the first standalone "--" before argparse sees it, so
    # the job's own flags are never mistaken for ours.
    argv = sys.argv[1:]
    command = []
    if "--" in argv:
        cut = argv.index("--")
        argv, command = argv[:cut], argv[cut + 1:]
    a = ap.parse_args(argv)
    if a.cmd == "start":
        if not command:
            raise SystemExit("give the command after --, e.g. run.py start census -- python tools/vault_census.py")
        raise SystemExit(start(a.name, command, a.resume, a.note))
    if a.cmd == "status":
        raise SystemExit(status(a.json, a.all, a.stall_after))
    if a.cmd == "log":
        log_cmd(a.id, a.tail)
    else:
        stop_cmd(a.id)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
