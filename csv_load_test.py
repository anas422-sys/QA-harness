"""Locust login/WebSocket test based on the supplied code, with Excel-ready CSVs.

Run: python csv_load_test.py --duration 60
Config: csv_load_devices.json. Password: RECHECK_PASSWORD or existing locustfile.py.
One virtual user per supplied device payload; payload contents are preserved.
"""
from gevent import monkey
monkey.patch_all()

import argparse
import ast
import base64
from collections import Counter
import csv
from datetime import datetime, timezone
import getpass
import json
import math
import os
from pathlib import Path
import plistlib
import sys
import time
import uuid
import gevent
from locust import User, task, between
from locust.env import Environment
from locust.exception import StopUser
import requests
import websocket

ROOT = Path(__file__).resolve().parent


def percentile(values, fraction):
    return round(sorted(values)[math.ceil(len(values) * fraction) - 1], 2) if values else ""


def safe_cell(value):
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({k: safe_cell(v) for k, v in row.items()} for row in rows)


def export_response(response, out):
    """Export a supplied server response locally. Commands remain text only."""
    if not isinstance(response, dict) or not isinstance(response.get("reply"), dict):
        raise ValueError("Expected a server response with a reply object")
    reply = response["reply"]
    info = reply.get("device_info", {})
    commands = reply.get("command", [])
    if not isinstance(info, dict) or not isinstance(commands, list) or any(not isinstance(c, dict) for c in commands):
        raise ValueError("device_info must be an object and command an array of objects")
    client = response.get("client_data", {})
    if not isinstance(client, dict):
        raise ValueError("client_data must be an object")
    metadata = dict(source="user_provided_response", udid=response.get("udid", ""),
                    username=response.get("username", ""), messagetype=response.get("messagetype", ""),
                    response_status=response.get("status", ""), request_ref=client.get("ref", ""),
                    measured_response_ms="", fresh_diagnostic_verified=False)
    # Known device-information fields only, not arbitrary response/credential fields.
    fields = ["model", "color", "storage", "imei_1", "imei_2", "serial_number", "firmware", "make",
              "build_version", "os_version", "region", "model_number", "product_type", "baseband_version",
              "is_activated", "current_date"]
    device = dict(metadata, **{key: info.get(key, "") for key in fields})
    command_rows = [dict(source=metadata["source"], udid=metadata["udid"], request_ref=metadata["request_ref"],
                         cmd_id=command.get("cmd_id", ""), command=command.get("cmd", ""), executed=False)
                    for command in commands]
    out.mkdir(parents=True, exist_ok=False)
    write_csv(out / "device_details.csv", [device], list(device))
    write_csv(out / "commands.csv", command_rows, ["source", "udid", "request_ref", "cmd_id", "command", "executed"])
    (out / "README.txt").write_text(
        "Exported from a user-provided response, not a new test run. No network requests or device commands were executed.\n"
        "Response status is supplied data, not independently verified. No response timing was provided.\n"
        "Empty cells preserve missing/empty values. Excel may auto-convert IDs: use Data > From Text/CSV and import identifier columns as Text.\n",
        encoding="utf-8")
    return out


def identity_matches(payload):
    if payload.get("device_operating_system") != "ios":
        return "not_checked"
    try:
        info = plistlib.loads(base64.b64decode(payload["device_info"]))
        return info.get("UniqueDeviceID") == payload["udid"]
    except (ValueError, KeyError, plistlib.InvalidFileException):
        return "unparseable"


def response_matches(reply, payload):
    return (isinstance(reply, dict) and reply.get("udid") == payload["udid"]
            and reply.get("messagetype") == payload["messagetype"]
            and isinstance(reply.get("client_data"), dict)
            and reply["client_data"].get("ref") == payload["client_data"]["ref"])


class KnownFailure(Exception):
    pass


class CsvRecorder:
    fields = ["run_mode", "timestamp_utc", "session", "platform", "device_id", "step", "request_ref",
              "response_ms", "response_bytes", "success", "error", "background_messages"]

    def __init__(self, out, mode="staging"):
        self.out = out
        self.mode = mode
        self.events = []
        self.users = []
        self.snapshots = []
        self.active = self.peak = 0
        self.handle = (out / "requests.csv").open("w", newline="", encoding="utf-8-sig")
        self.writer = csv.DictWriter(self.handle, fieldnames=self.fields)
        self.writer.writeheader()

    def record(self, user, step, elapsed, length, error, reference="", background=0):
        row = dict(run_mode=self.mode, timestamp_utc=datetime.now(timezone.utc).isoformat(), session=user.label,
                   platform=user.payload["device_operating_system"], device_id=user.payload["udid"],
                   step=step, request_ref=reference, response_ms=round(elapsed, 2), response_bytes=length,
                   success=error is None, error=error or "", background_messages=background)
        self.events.append(row)
        self.writer.writerow({k: safe_cell(v) for k, v in row.items()})
        self.handle.flush()

    def finish(self, target, elapsed, interrupted):
        self.handle.close()
        devices = []
        for user in self.users:
            rows = [e for e in self.events if e["session"] == user.label]
            actions = [e for e in rows if e["step"] == "device_request"]
            times = [e["response_ms"] for e in actions if e["success"]]
            devices.append(dict(run_mode=self.mode, session=user.label, platform=user.payload["device_operating_system"],
                                device_id=user.payload["udid"], embedded_udid_matches=identity_matches(user.payload),
                                login_ok=any(e["step"] == "login" and e["success"] for e in rows),
                                connection_ok=any(e["step"] == "connect" and e["success"] for e in rows),
                                requests=len(actions), acknowledged=sum(e["success"] for e in actions),
                                failed_operations=sum(not e["success"] for e in rows),
                                request_p50_ms=percentile(times, .5), request_p95_ms=percentile(times, .95),
                                request_max_ms=max(times) if times else "", diagnostics_verified=0,
                                difficulties="; ".join(sorted({e["step"] + ": " + e["error"] for e in rows if e["error"]}))))
        write_csv(self.out / "devices.csv", devices, list(devices[0]) if devices else ["session"])
        platforms = []
        for platform in sorted({d["platform"] for d in devices}):
            subset = [d for d in devices if d["platform"] == platform]
            times = [e["response_ms"] for e in self.events if e["platform"] == platform and e["step"] == "device_request" and e["success"]]
            platforms.append(dict(run_mode=self.mode, platform=platform, sessions=len(subset), unique_device_ids=len({d["device_id"] for d in subset}),
                                  connected=sum(d["connection_ok"] for d in subset), requests=sum(d["requests"] for d in subset),
                                  acknowledged=sum(d["acknowledged"] for d in subset), failed_operations=sum(d["failed_operations"] for d in subset),
                                  successful_request_p95_ms=percentile(times, .95), diagnostics_verified=0))
        write_csv(self.out / "platform_summary.csv", platforms, list(platforms[0]) if platforms else ["platform"])
        write_csv(self.out / "diagnostic_results.csv", self.snapshots,
                  ["run_mode", "received_at_utc", "session", "platform", "device_id", "test_code", "test_name", "reported_result", "fresh_run_verified"])
        summary = dict(run_mode=self.mode, target_sessions=target, started_sessions=len(devices), peak_connections=self.peak,
                       elapsed_seconds=round(elapsed, 2), interrupted=interrupted,
                       failed_operations=sum(d["failed_operations"] for d in devices),
                       fixture_identity_mismatches=sum(d["embedded_udid_matches"] is False for d in devices),
                       acknowledged_requests=sum(d["acknowledged"] for d in devices), verified_diagnostics=0)
        summary["sessions_with_acknowledgments"] = sum(d["acknowledged"] > 0 for d in devices)
        write_csv(self.out / "run_summary.csv", [summary], list(summary))
        notes = ("Login/connect failures are included. Each original fixture is assigned to one session.\n"
                 "Request success means status=success with matching UDID, message type and reference.\n"
                 "Percentiles cover successful device-request replies, not login, failures, screen times or hardware diagnostics.\n"
                 "Requests.csv includes failed operation durations. Diagnostic CSV contains only observed type-15 snapshots; no fresh completion is inferred.\n"
                 "Original device_info is preserved. Inspect embedded_udid_matches: mismatches prevent claiming realistic distinct-device coverage.\n"
                 "All sessions share one account. Failed sessions stop rather than silently reconnecting.\n"
                 "Background messages are filtered; the response timeout applies to the whole wait, not each unrelated message.\n")
        (self.out / "README.txt").write_text(notes, encoding="utf-8")
        return summary


class WebSocketUser(User):
    wait_time = between(1, 3)

    def on_start(self):
        self.cfg = self.environment.test_config
        self.recorder = self.environment.csv_recorder
        index = len(self.recorder.users)
        self.label = f"session-{index + 1:02d}"
        self.payload = json.loads(json.dumps(self.cfg["devices"][index]))
        self.recorder.users.append(self)
        self.ws = None
        self.opened = False
        self.http = requests.Session()
        self.token = self.measure("login", self.login)
        self.measure("connect", self.connect)

    def measure(self, step, operation, reference=""):
        started = time.perf_counter()
        error = None
        result = None
        self.response_bytes = self.background = 0
        try:
            result = operation()
        except gevent.GreenletExit:
            error = "interrupted"
            raise
        except Exception as exc:
            error = str(exc) if isinstance(exc, KnownFailure) else type(exc).__name__
            if isinstance(exc, websocket.WebSocketBadStatusException):
                error = "HTTP " + str(exc.status_code)
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            self.recorder.record(self, step, elapsed, self.response_bytes, error, reference, self.background)
            self.environment.events.request.fire(request_type="HTTP" if step == "login" else "WS", name=step,
                response_time=elapsed, response_length=self.response_bytes, exception=KnownFailure(error) if error else None,
                context={"session": self.label, "platform": self.payload["device_operating_system"]})
        if error:
            raise StopUser()
        return result

    def login(self):
        with self.http.post(self.cfg["login_url"], json={"username": self.cfg["username"], "password": self.cfg["password"]},
                            timeout=self.cfg["timeout"], allow_redirects=False) as response:
            self.response_bytes = len(response.content)
            if response.status_code != 200:
                raise KnownFailure("HTTP " + str(response.status_code))
            data = response.json()
            nested = data.get("data") or {}
            token = data.get("access_token") or data.get("token") or nested.get("token") or nested.get("access_token")
            if not isinstance(token, str) or not token:
                raise KnownFailure("missing token")
            return token

    def connect(self):
        self.ws = websocket.create_connection(self.cfg["ws_url"], header={"Authorization": "Bearer " + self.token}, timeout=self.cfg["timeout"])
        self.opened = True
        self.recorder.active += 1
        self.recorder.peak = max(self.recorder.peak, self.recorder.active)

    def exchange(self):
        self.ws.send(json.dumps(self.payload))
        deadline = time.monotonic() + self.cfg["timeout"]
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise KnownFailure("matching response timeout")
            self.ws.settimeout(remaining)
            raw = self.ws.recv()
            if not raw:
                raise KnownFailure("connection closed")
            self.response_bytes += len(raw.encode("utf-8") if isinstance(raw, str) else raw)
            try:
                reply = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                self.background += 1
                continue
            if isinstance(reply, dict) and reply.get("messagetype") == 15 and reply.get("udid") == self.payload["udid"]:
                content = reply.get("reply") or {}
                if reply.get("status") == "success" and isinstance(content, dict) and isinstance(content.get("tests"), list):
                    for test in content["tests"]:
                        if isinstance(test, dict):
                            self.recorder.snapshots.append(dict(run_mode=self.recorder.mode, received_at_utc=datetime.now(timezone.utc).isoformat(), session=self.label,
                                platform=self.payload["device_operating_system"], device_id=self.payload["udid"],
                                test_code=test.get("code", ""), test_name=test.get("test_name", ""), reported_result=test.get("result", ""), fresh_run_verified=False))
            if not response_matches(reply, self.payload):
                self.background += 1
                continue
            if reply.get("status") != "success":
                raise KnownFailure("application response not successful")
            return reply

    @task
    def task_send_message(self):
        if self.cfg.get("stopping"):
            raise StopUser()
        self.payload["client_data"] = {"ref": int(uuid.uuid4().hex[:13], 16)}
        self.measure("device_request", self.exchange, self.payload["client_data"]["ref"])

    def on_stop(self):
        if self.opened:
            self.recorder.active -= 1
            self.opened = False
        if self.ws:
            try:
                self.ws.close(timeout=1)
            except Exception:
                pass
        self.http.close()


def start_demo(cfg):
    """Loopback HTTP/WS servers with synthetic data, not staging emulation."""
    from gevent.pywsgi import WSGIServer
    from websockets.sync.server import serve
    from websockets.exceptions import ConnectionClosed
    def login_app(environ, start_response):
        length = int(environ.get("CONTENT_LENGTH") or 0)
        environ["wsgi.input"].read(length)
        start_response("200 OK", [("Content-Type", "application/json")])
        return [b'{"token":"local-demo-token"}']
    http = WSGIServer(("127.0.0.1", 0), login_app, log=None)
    http.start()
    def echo(connection):
        try:
            for message in connection:
                payload = json.loads(message)
                connection.send("synthetic background event")
                connection.send(json.dumps(dict(payload, status="success")))
        except ConnectionClosed:
            pass
    ws = serve(echo, "127.0.0.1", 0)
    greenlet = gevent.spawn(ws.serve_forever)
    cfg.update(login_url=f"http://127.0.0.1:{http.server_port}/login",
               ws_url=f"ws://127.0.0.1:{ws.socket.getsockname()[1]}")
    def stop():
        ws.shutdown()
        http.stop()
        greenlet.join(timeout=2)
    return stop


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "csv_load_devices.json")
    parser.add_argument("--users", type=int, help="Defaults to one user per supplied device (14 in the attached code).")
    parser.add_argument("--duration", type=int, default=60, help="Total seconds including ramp-up.")
    parser.add_argument("--spawn-rate", type=float, default=2)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--output-root", type=Path, default=ROOT / "reports")
    parser.add_argument("--demo", action="store_true", help="Local synthetic demonstration; no staging requests or private fixtures.")
    parser.add_argument("--response-json", type=Path, help="Export one saved server response to CSV locally; does not run a load test.")
    args = parser.parse_args()
    if args.response_json:
        if args.demo:
            parser.error("Choose either --response-json or --demo")
        response = json.loads(args.response_json.read_text(encoding="utf-8-sig"))
        out = args.output_root / datetime.now(timezone.utc).strftime("response-csv-%Y%m%dT%H%M%S%fZ")
        export_response(response, out)
        print("Response CSVs:", out)
        return 0
    if args.demo:
        cfg = dict(username="local-demo", devices=[dict(udid=f"DEMO-IOS-{i:02d}", device_operating_system="ios",
            messagetype=1, device_info=base64.b64encode(plistlib.dumps({"UniqueDeviceID": f"DEMO-IOS-{i:02d}"})).decode()) for i in range(1, 15)])
    else:
        cfg = json.loads(args.config.read_text(encoding="utf-8-sig"))
    count = args.users if args.users is not None else len(cfg["devices"])
    if not 1 <= count <= len(cfg["devices"]) or args.duration < 1 or not math.isfinite(args.spawn_rate) or args.spawn_rate <= 0 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("Use positive duration/rate/timeout and no more users than supplied payloads.")
    cfg["devices"] = cfg["devices"][:count]
    ids = [p.get("udid") for p in cfg["devices"]]
    if not all(isinstance(x, str) and x for x in ids) or len(set(ids)) != count:
        parser.error("Each payload needs a different nonempty udid.")
    for payload in cfg["devices"]:
        if payload.get("device_operating_system") not in ("ios", "android") or "messagetype" not in payload:
            parser.error("Each payload needs device_operating_system and messagetype.")
    password = "local-demo" if args.demo else os.environ.get(cfg.get("password_env", "RECHECK_PASSWORD"))
    if not password and (ROOT / "locustfile.py").exists():
        source = ast.parse((ROOT / "locustfile.py").read_text(encoding="utf-8-sig"))
        values = {}
        for node in ast.walk(source):
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ("USERNAME", "PASSWORD"):
                values[node.targets[0].id] = ast.literal_eval(node.value)
        if values.get("USERNAME") == cfg["username"]:
            password = values.get("PASSWORD")
    if not password and sys.stdin.isatty():
        password = getpass.getpass("Staging password: ")
    if not password:
        parser.error("Set RECHECK_PASSWORD or provide matching credentials in locustfile.py.")
    cfg.update(password=password, timeout=args.timeout)
    out = args.output_root / datetime.now(timezone.utc).strftime(("csv-demo-" if args.demo else "csv-load-") + "%Y%m%dT%H%M%S%fZ")
    out.mkdir(parents=True)
    stop_demo = start_demo(cfg) if args.demo else None
    recorder = CsvRecorder(out, "local_demo" if args.demo else "staging")
    env = Environment(user_classes=[WebSocketUser], stop_timeout=args.timeout + 2)
    env.test_config, env.csv_recorder = cfg, recorder
    runner = env.create_local_runner()
    started = time.monotonic()
    interrupted = False
    try:
        runner.start(count, spawn_rate=args.spawn_rate)
        print(f"Running {count} sessions for {args.duration}s. CSV folder: {out}", flush=True)
        gevent.sleep(args.duration)
    except KeyboardInterrupt:
        interrupted = True
    finally:
        cfg["stopping"] = True
        # Let each in-flight exchange finish and prevent the next task from starting.
        runner.user_greenlets.join(timeout=args.timeout + 4)
        runner.quit()
        if stop_demo:
            stop_demo()
        summary = recorder.finish(count, time.monotonic() - started, interrupted)
    print(json.dumps(summary, indent=2))
    print("Open:", out / "platform_summary.csv")
    return 1 if interrupted or summary["failed_operations"] or summary["started_sessions"] < count or summary["sessions_with_acknowledgments"] < count else 0


if __name__ == "__main__":
    raise SystemExit(main())
