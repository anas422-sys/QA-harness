"""Daily QA agents for the reCheck360 staging environment."""
from __future__ import annotations

import argparse
import ast
import csv
from datetime import datetime
import html
import json
from pathlib import Path
import subprocess
import time
import uuid

import requests
import websocket


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent


def load_credentials():
    tree = ast.parse((WORKSPACE / "locustfile.py").read_text(encoding="utf-8-sig"))
    names = {"USERNAME", "PASSWORD"}
    values = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and node.targets
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in names
    }
    if set(values) != names:
        raise RuntimeError("USERNAME and PASSWORD were not found in locustfile.py")
    return values


def result(agent, category, name, status, duration_ms="", details="", evidence=""):
    return {
        "agent": agent,
        "category": category,
        "test": name,
        "status": status,
        "duration_ms": duration_ms,
        "details": details,
        "evidence": evidence,
    }


def frontend_agent(config):
    rows = []
    started = time.perf_counter()
    try:
        output = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=10, check=True
        ).stdout.lower()
        matches = [key for key in config["desktop_process_keywords"] if key.lower() in output]
        rows.append(result(
            "Frontend QA Agent", "Frontend automated", "Desktop application process",
            "PASS" if matches else "FAIL",
            round((time.perf_counter() - started) * 1000, 2),
            "Detected: " + ", ".join(matches) if matches else "reCheck360 process was not detected",
        ))
    except Exception as exc:
        rows.append(result("Frontend QA Agent", "Frontend automated", "Desktop application process", "ERROR",
                           round((time.perf_counter() - started) * 1000, 2), type(exc).__name__))
    for check in config["frontend_manual_checks"]:
        rows.append(result("Frontend QA Agent", "Frontend manual", check, "PENDING MANUAL",
                           details="A tester must perform and record this visual or interactive check"))
    return rows


def receive_correlated(ws, kind, ref, timeout):
    deadline = time.monotonic() + timeout
    extras = 0
    while time.monotonic() < deadline:
        ws.settimeout(max(0.01, deadline - time.monotonic()))
        try:
            opcode, raw = ws.recv_data(control_frame=True)
        except websocket.WebSocketTimeoutException:
            break
        if opcode in (websocket.ABNF.OPCODE_PING, websocket.ABNF.OPCODE_PONG):
            continue
        if opcode == websocket.ABNF.OPCODE_CLOSE:
            raise ConnectionError("WebSocket closed")
        try:
            message = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            extras += 1
            continue
        if (isinstance(message, dict) and message.get("messagetype") == kind
                and isinstance(message.get("client_data"), dict)
                and message["client_data"].get("ref") == ref):
            return message, extras
        extras += 1
    return None, extras


def backend_agent(config):
    rows = []
    credentials = load_credentials()
    timeout = config["response_timeout_seconds"]
    session = requests.Session()
    token = None
    started = time.perf_counter()
    try:
        response = session.post(
            config["login_url"],
            json={"username": credentials["USERNAME"], "password": credentials["PASSWORD"]},
            timeout=timeout,
            allow_redirects=False,
        )
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        body = response.json() if response.content else {}
        nested = body.get("data") or {}
        token = body.get("token") or body.get("access_token") or nested.get("token") or nested.get("access_token")
        status = "PASS" if response.status_code == 200 and isinstance(token, str) and token else "FAIL"
        rows.append(result("Backend QA Agent", "Backend automated", "Authentication API", status, elapsed,
                           f"HTTP {response.status_code}; token present: {bool(token)}"))
    except Exception as exc:
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        rows.append(result("Backend QA Agent", "Backend automated", "Authentication API", "ERROR", elapsed,
                           type(exc).__name__))

    ws = None
    if token:
        started = time.perf_counter()
        try:
            ws = websocket.create_connection(
                config["ws_url"], header={"Authorization": "Bearer " + token}, timeout=timeout
            )
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            rows.append(result("Backend QA Agent", "Backend automated", "WebSocket connection", "PASS", elapsed,
                               "Authenticated connection opened"))

            ref = uuid.uuid4().int >> 76
            payload = {
                "messagetype": 119,
                "client_data": {"ref": ref},
                "app_version": "1.7.7",
                "operating_system": "windows",
                "architecture": "x64",
            }
            started = time.perf_counter()
            ws.send(json.dumps(payload))
            reply, extras = receive_correlated(ws, 119, ref, timeout)
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            if reply is None:
                status, details = "TIMEOUT", f"No correlated reply in {timeout} seconds; additional messages: {extras}"
            elif reply.get("status") != "success":
                status, details = "FAIL", str(reply.get("message", "Server returned a non-success status"))
            else:
                status = "SLOW" if elapsed > config["slow_threshold_ms"] else "PASS"
                details = f"Correlated success; additional messages: {extras}"
            rows.append(result("Backend QA Agent", "Backend automated", "Version message contract", status,
                               elapsed, details, f"message type 119 ref {ref}"))
        except Exception as exc:
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            rows.append(result("Backend QA Agent", "Backend automated", "WebSocket connection or message", "ERROR",
                               elapsed, type(exc).__name__))
        finally:
            if ws:
                try:
                    ws.close(timeout=1)
                except Exception:
                    pass
    else:
        rows.append(result("Backend QA Agent", "Backend automated", "WebSocket checks", "BLOCKED",
                           details="Authentication did not provide a token"))

    for check in config["backend_manual_checks"]:
        rows.append(result("Backend QA Agent", "Backend manual", check, "PENDING MANUAL",
                           details="Requires backend log database or operational access"))
    return rows


def write_csv(path, rows):
    fields = ["agent", "category", "test", "status", "duration_ms", "details", "evidence"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def dashboard(path, run, rows):
    counts = {status: sum(r["status"] == status for r in rows) for status in
              ("PASS", "FAIL", "ERROR", "TIMEOUT", "SLOW", "BLOCKED", "PENDING MANUAL")}
    colors = {"PASS": "#17803d", "FAIL": "#b42318", "ERROR": "#b42318", "TIMEOUT": "#b54708",
              "SLOW": "#b54708", "BLOCKED": "#667085", "PENDING MANUAL": "#175cd3"}
    cards = "".join(
        f'<div class="card"><span>{html.escape(k)}</span><strong style="color:{colors[k]}">{v}</strong></div>'
        for k, v in counts.items() if v
    )
    sections = []
    for agent in ("Frontend QA Agent", "Backend QA Agent"):
        body = []
        for row in [r for r in rows if r["agent"] == agent]:
            status = row["status"]
            body.append(
                "<tr>"
                f'<td>{html.escape(row["category"])}</td><td>{html.escape(row["test"])}</td>'
                f'<td><span class="badge" style="background:{colors.get(status, "#667085")}">{html.escape(status)}</span></td>'
                f'<td>{html.escape(str(row["duration_ms"]))}</td><td>{html.escape(row["details"])}</td>'
                "</tr>"
            )
        sections.append(f"<h2>{agent}</h2><table><thead><tr><th>Type</th><th>Test</th><th>Status</th><th>ms</th><th>Details</th></tr></thead><tbody>{''.join(body)}</tbody></table>")
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Daily QA Dashboard</title>
<style>body{{font-family:Segoe UI,Arial;margin:0;background:#f4f7fb;color:#172b4d}}main{{max-width:1200px;margin:auto;padding:30px}}h1{{margin-bottom:4px}}.meta{{color:#667085}}.cards{{display:flex;gap:12px;flex-wrap:wrap;margin:22px 0}}.card{{background:white;border:1px solid #dde3ea;border-radius:10px;padding:13px 18px;min-width:130px;display:flex;justify-content:space-between;gap:18px}}.card strong{{font-size:22px}}h2{{margin-top:28px}}table{{width:100%;border-collapse:collapse;background:white;border-radius:10px;overflow:hidden}}th{{background:#17365d;color:white;text-align:left}}th,td{{padding:10px;border:1px solid #d9d9d9;vertical-align:top}}tr:nth-child(even){{background:#f7f9fc}}.badge{{color:white;font-weight:700;padding:4px 8px;border-radius:12px;white-space:nowrap}}.note{{margin-top:22px;background:#fff8e6;border-left:4px solid #f79009;padding:12px}}</style></head>
<body><main><h1>Daily QA Dashboard</h1><div class="meta">Environment: {html.escape(run['environment'])} | Run: {html.escape(run['started_at'])}</div><div class="cards">{cards}</div>{''.join(sections)}<div class="note"><strong>Manual testing:</strong> items marked PENDING MANUAL require a tester to interact with the desktop application or inspect restricted backend systems. The automated agent does not mark them as passed.</div></main></body></html>"""
    path.write_text(page, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8-sig"))
    started = datetime.now().astimezone()
    out = ROOT / "reports" / started.strftime("%Y-%m-%d_%H%M%S")
    out.mkdir(parents=True)
    rows = frontend_agent(config) + backend_agent(config)
    run = {"environment": config["environment"], "started_at": started.isoformat(timespec="seconds"), "results": rows}
    (out / "results.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    write_csv(out / "results.csv", rows)
    dashboard(out / "dashboard.html", run, rows)
    dashboard(ROOT / "latest_dashboard.html", run, rows)
    (ROOT / "latest_report.txt").write_text(str(out.resolve()), encoding="utf-8")
    print(out.resolve())
    print(json.dumps({status: sum(r["status"] == status for r in rows) for status in set(r["status"] for r in rows)}, indent=2))
    return 1 if any(r["status"] in ("FAIL", "ERROR", "TIMEOUT") for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
