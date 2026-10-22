    """Measure concurrent login + WebSocket transport sessions using existing staging settings."""
import argparse
import ast
import csv
import json
import math
from pathlib import Path
import threading
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import requests
import websocket

ROOT = Path(__file__).resolve().parent


def settings():
    tree = ast.parse((ROOT/"locustfile.py").read_text(encoding="utf-8-sig"))
    names = {"LOGIN_URL", "WS_URL", "USERNAME", "PASSWORD"}
    result = {n.targets[0].id: ast.literal_eval(n.value) for n in ast.walk(tree)
              if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
              and n.targets[0].id in names}
    if set(result) != names:
        raise ValueError("Missing login/WebSocket settings in locustfile.py")
    return result


def percentile(values, fraction):
    return round(sorted(values)[max(0, math.ceil(len(values)*fraction)-1)], 2) if values else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--hold", type=int, default=60, help="Seconds after all users finish starting.")
    parser.add_argument("--spawn-rate", type=float, default=2)
    args = parser.parse_args()
    if not 1 <= args.users <= 20 or args.hold < 5 or args.spawn_rate <= 0:
        parser.error("users must be 1..20; hold >=5; spawn-rate >0")
    cfg = settings()
    out = ROOT/"reports"/datetime.now(timezone.utc).strftime("transport-%Y%m%dT%H%M%S%fZ")
    out.mkdir(parents=True)
    lock = threading.Lock()
    stop = threading.Event()
    startup = [threading.Event() for _ in range(args.users)]
    events = []
    history = []
    rows = [dict(user_id=f"session-{i+1:02d}", login_ok=False, connection_ok=False,
                 successful_pongs=0, failures=0, difficulties=[]) for i in range(args.users)]
    active = 0
    peak = 0
    start = time.monotonic()

    def record(row, step, started, error=None):
        item = dict(user_id=row["user_id"], step=step,
                    elapsed_s=round(time.monotonic()-start, 3),
                    duration_ms=round((time.perf_counter()-started)*1000, 2),
                    error=error)
        with lock:
            events.append(item)
            if error:
                row["failures"] += 1
                row["difficulties"].append(step+": "+error)

    def worker(index):
        nonlocal active, peak
        row = rows[index]
        ws = None
        counted = False
        step = "login"
        started = time.perf_counter()
        try:
            with requests.Session() as client:
                with client.post(cfg["LOGIN_URL"], json={"username":cfg["USERNAME"],"password":cfg["PASSWORD"]},
                                 timeout=15, allow_redirects=False) as response:
                    if response.status_code != 200:
                        raise ValueError("HTTP "+str(response.status_code))
                    data = response.json()
                    nested = data.get("data") or {}
                    token = data.get("token") or data.get("access_token") or nested.get("token") or nested.get("access_token")
                    if not isinstance(token, str) or not token:
                        raise ValueError("missing token")
                row["login_ok"] = True
                record(row, step, started)
                step = "connect"
                started = time.perf_counter()
                ws = websocket.create_connection(cfg["WS_URL"],header={"Authorization":"Bearer "+token},timeout=10)
                row["connection_ok"] = True
                with lock:
                    active += 1
                    counted = True
                    peak = max(peak, active)
                    history.append(dict(elapsed_s=round(time.monotonic()-start,3), open_sessions=active))
                record(row, step, started)
                startup[index].set()
                while not stop.is_set():
                    step = "ping_pong"
                    started = time.perf_counter()
                    marker = (row["user_id"]+"-"+str(row["successful_pongs"])).encode()
                    ws.ping(marker)
                    deadline = time.monotonic()+10
                    while True:
                        remaining = deadline-time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError()
                        ws.settimeout(remaining)
                        opcode, frame = ws.recv_data_frame(control_frame=True)
                        if opcode == websocket.ABNF.OPCODE_CLOSE:
                            raise ConnectionError()
                        if opcode == websocket.ABNF.OPCODE_PONG and frame.data == marker:
                            break
                    row["successful_pongs"] += 1
                    record(row, step, started)
                    stop.wait(5)
        except Exception as error:
            # Never persist arbitrary exception messages: they may contain tokens or bodies.
            category = str(error) if type(error) is ValueError and (str(error).startswith("HTTP ") or str(error)=="missing token") else type(error).__name__
            record(row, step, started, category)
        finally:
            startup[index].set()
            if counted:
                with lock:
                    active -= 1
                    history.append(dict(elapsed_s=round(time.monotonic()-start,3),open_sessions=active))
            if ws:
                try:
                    ws.close(timeout=1)
                except Exception:
                    pass

    with ThreadPoolExecutor(max_workers=args.users) as pool:
        jobs = []
        for index in range(args.users):
            jobs.append(pool.submit(worker,index))
            if index+1 < args.users:
                time.sleep(1/args.spawn_rate)
        for ready in startup:
            ready.wait()
        with lock:
            held_at_start = active
        hold_started = time.monotonic()
        print(f"Started {args.users} sessions; {held_at_start} sockets open. Holding for {args.hold}s.",flush=True)
        try:
            stop.wait(args.hold)
        finally:
            with lock:
                held_at_end = active
            stop.set()
        for job in jobs:
            job.result()
    by_step = {}
    for step in ("login","connect","ping_pong"):
        samples = [e for e in events if e["step"]==step]
        times = [e["duration_ms"] for e in samples if e["error"] is None]
        by_step[step] = dict(attempts=len(samples), failures=sum(e["error"] is not None for e in samples),
                            successful_p50_ms=percentile(times,.5),successful_p95_ms=percentile(times,.95),
                            successful_max_ms=max(times) if times else None)
    summary = dict(scope="shared-account login and WebSocket transport only",
                   target_sessions=args.users, peak_open_sessions=peak,
                   open_sessions_at_hold_start=held_at_start,open_sessions_at_hold_end=held_at_end,
                   requested_hold_seconds=args.hold,elapsed_seconds=round(time.monotonic()-start,2),
                   failures=sum(r["failures"] for r in rows),steps=by_step,users=rows,connection_history=history)
    passed = held_at_start==args.users and held_at_end==args.users and summary["failures"]==0 and all(r["successful_pongs"]>0 for r in rows)
    summary["transport_check"] = "PASS" if passed else "FAIL"
    (out/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    with (out/"users.csv").open("w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (out/"events.csv").open("w",newline="",encoding="utf-8") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(events[0]))
        writer.writeheader()
        writer.writerows(events)
    lines=["# Concurrent session performance report","",
           f"Transport check: {summary['transport_check']}. Target: {args.users} sessions.",
           f"Peak sockets: {peak}; hold start/end: {held_at_start}/{held_at_end}. Hold: {args.hold}s.",
           f"Failed operations: {summary['failures']}.", "",
           "| Step | Attempts | Failures | Successful p50 ms | Successful p95 ms |",
           "|---|---:|---:|---:|---:|"]
    for step,item in by_step.items():
        lines.append(f"| {step} | {item['attempts']} | {item['failures']} | {item['successful_p50_ms']} | {item['successful_p95_ms']} |")
    lines += ["","## Difficulties",""]
    difficulties=[f"- {r['user_id']}: {', '.join(r['difficulties'])}" for r in rows if r["difficulties"]]
    lines += difficulties or ["- No login, connection, or ping/pong failures observed."]
    lines += ["","## Meaning and limits","",
              "Login/setup times indicate potential waiting before connection; ping/pong measures network and WebSocket transport responsiveness.",
              "These are simulated sessions sharing one account. Open sockets and pong replies do not establish that all sessions retain application authorization.",
              "No diagnostic payloads were sent. No USB, hardware diagnostics, desktop UI response, or subjective user experience was measured.",
              "This is an initial 20-session load probe, not a breaking-point stress test or proof of diagnostic capacity.",
              "PASS means connections survived this interval with successful heartbeat checks; no product latency SLA was supplied.",
              "Next: validate a diagnostic request/result contract, supply distinct test accounts/consistent synthetic fixtures, then run sustained diagnostic traffic."]
    (out/"experience_report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in summary.items() if k not in ("users","connection_history")},indent=2))
    print(f"Report: {out/'experience_report.md'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

