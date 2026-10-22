"""Validate observed WebSocket message flows; never execute returned commands.

python validate_message_flow.py --reference-log PATH --per-platform 10
Uses existing staging credentials via run_session_load.py and synthetic fixtures.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid
import requests
import websocket
from run_session_load import settings
from run_dummy_devices import fixture

ROOT = Path(__file__).resolve().parent
EXCLUDED = {18: "logout can invalidate shared account sessions", 134: "session creation changes application state"}
DYNAMIC = {"token", "hub_token", "access_token", "current_date", "timestamp", "expires_at", "client_data", "udid", "username"}


def fingerprint(value):
    def clean(v):
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items() if k not in DYNAMIC}
        if isinstance(v, list):
            return sorted([clean(x) for x in v], key=lambda x: json.dumps(x, sort_keys=True))
        return v
    return hashlib.sha256(json.dumps(clean(value), sort_keys=True).encode()).hexdigest()


def schema(value):
    if isinstance(value, dict):
        return {"type": "object", "fields": {k: schema(v) for k, v in value.items()}}
    if isinstance(value, list):
        variants = {json.dumps(schema(v), sort_keys=True): schema(v) for v in value}
        return {"type": "array", "nonempty": bool(value), "items": list(variants.values())}
    return {"type": type(value).__name__}


def compare(expected, actual, path="reply"):
    kind = expected["type"]
    actual_kind = "object" if isinstance(actual, dict) else "array" if isinstance(actual, list) else type(actual).__name__
    if kind != actual_kind:
        return [f"{path}: expected {kind}, received {actual_kind}"]
    issues = []
    if kind == "object":
        for key, child in expected["fields"].items():
            if key not in actual:
                issues.append(f"{path}.{key}: missing")
            else:
                issues.extend(compare(child, actual[key], path + "." + key))
    elif kind == "array":
        if expected["nonempty"] and not actual:
            issues.append(path + ": expected nonempty list")
        for index, item in enumerate(actual):
            if expected["items"]:
                issues.extend(min((compare(s, item, f"{path}[{index}]") for s in expected["items"]), key=len))
    return issues


def build_reference(path):
    pending, contracts, coverage = {}, {}, []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        if "WebSocketManager" not in line or "{" not in line:
            continue
        try:
            obj = json.JSONDecoder().raw_decode(line[line.index("{"):])[0]
        except ValueError:
            continue
        if not isinstance(obj, dict) or not isinstance(obj.get("client_data"), dict):
            continue
        key = (obj.get("messagetype"), obj["client_data"].get("ref"))
        if "Message sent:" in line:
            pending[key] = obj
        elif "Received message:" in line and key in pending:
            request = pending.pop(key)
            kind = request["messagetype"]
            if kind in EXCLUDED:
                coverage.append(dict(message_type=kind, outcome="EXCLUDED", reason=EXCLUDED[kind]))
                continue
            if obj.get("status") != "success" or "reply" not in obj:
                coverage.append(dict(message_type=kind, outcome="NO_SUCCESS_REFERENCE", reason="no successful reply payload"))
                continue
            payload = {k: v for k, v in request.items() if k != "client_data"}
            signature = json.dumps(payload, sort_keys=True)
            contract = contracts.setdefault(signature, dict(payload=payload, schemas=[], fingerprints=[]))
            form = schema(obj["reply"])
            if form not in contract["schemas"]:
                contract["schemas"].append(form)
            value_hash = fingerprint(obj["reply"])
            if value_hash not in contract["fingerprints"]:
                contract["fingerprints"].append(value_hash)
    for request in pending.values():
        kind = request["messagetype"]
        coverage.append(dict(message_type=kind, outcome="EXCLUDED" if kind in EXCLUDED else "NO_MATCHING_REPLY_IN_LOG",
                             reason=EXCLUDED.get(kind, "not evidence of a server failure")))
    return list(contracts.values()), coverage


def csv_file(path, rows, fields):
    def safe(value):
        return "'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")) else value
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({k: safe(v) for k, v in row.items()} for row in rows)


def envelope_issue(reply, payload, username):
    if reply.get("status") != "success":
        return "APPLICATION_FAILURE", "status was not success"
    if "username" not in reply or ("udid" in payload and "udid" not in reply):
        return "SCHEMA_MISMATCH", "correlated success reply is missing an account/device identity field"
    if reply["username"] != username or ("udid" in payload and reply["udid"] != payload["udid"]):
        return "ISOLATION_MISMATCH", "explicit account/device identity differs from request"
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-log", type=Path, required=True)
    parser.add_argument("--per-platform", type=int, default=10)
    parser.add_argument("--spawn-rate", type=float, default=2)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--slow-ms", type=float, default=2000, help="Provisional slow-response flag, not a product SLA.")
    args = parser.parse_args()
    if not 1 <= args.per_platform <= 10 or not 0 < args.spawn_rate <= 20 or not 0 < args.timeout <= 60:
        parser.error("per-platform 1..10, spawn-rate 0..20, timeout 0..60")
    contracts, coverage = build_reference(args.reference_log)
    if not contracts:
        parser.error("No matched successful exchanges in reference log")
    cfg = settings()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = ROOT / "reports" / ("flow-validation-" + stamp)
    out.mkdir(parents=True)
    (out / "reference_contract.json").write_text(json.dumps(contracts, indent=2), encoding="utf-8")
    csv_file(out / "reference_gaps.csv", coverage, ["message_type", "outcome", "reason"])
    rows, lock = [], threading.Lock()
    def worker(platform, index):
        device = fixture(platform, index, stamp)
        label = f"{platform}-{index:02d}"
        def record(kind, variant, outcome, started, details="", unrelated=0):
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            row = dict(session=label, platform=platform, dummy_udid=device["udid"], message_type=kind,
                       variant=variant, outcome=outcome, response_ms=elapsed, slow=elapsed > args.slow_ms,
                       details=details, background_messages=unrelated)
            with lock:
                rows.append(row)
        ws = None
        started = time.perf_counter()
        startup_step = "login"
        try:
            with requests.Session() as http:
                with http.post(cfg["LOGIN_URL"], json={"username": cfg["USERNAME"], "password": cfg["PASSWORD"]}, timeout=args.timeout, allow_redirects=False) as response:
                    if response.status_code != 200:
                        raise RuntimeError("HTTP " + str(response.status_code))
                    body = response.json()
                    nested = body.get("data") or {}
                    token = body.get("token") or body.get("access_token") or nested.get("token") or nested.get("access_token")
                    if not isinstance(token, str) or not token:
                        raise RuntimeError("missing token")
                record("login", "", "PASS", started)
                startup_step = "connect"
                started = time.perf_counter()
                ws = websocket.create_connection(cfg["WS_URL"], header={"Authorization": "Bearer " + token}, timeout=args.timeout)
                record("connect", "", "PASS", started)
        except Exception as exc:
            category = str(exc) if type(exc) is RuntimeError else type(exc).__name__
            record(startup_step, "", "ERROR", started, category)
        steps = contracts + [dict(payload=device, schemas=[], fingerprints=[])]
        try:
            for contract in steps:
                payload = json.loads(json.dumps(contract["payload"]))
                kind = payload["messagetype"]
                variant = str(payload.get("os", payload.get("test_plan_name", payload.get("app_version", ""))))
                started = time.perf_counter()
                if ws is None:
                    record(kind, variant, "NOT_RUN", started, "session unavailable after earlier failure")
                    continue
                ref = int(uuid.uuid4().hex[:13], 16)
                payload["client_data"] = {"ref": ref}
                background = 0
                try:
                    ws.send(json.dumps(payload))
                    deadline = time.monotonic() + args.timeout
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError()
                        ws.settimeout(remaining)
                        raw = ws.recv()
                        if not raw:
                            raise ConnectionError()
                        try:
                            reply = json.loads(raw)
                        except (ValueError, UnicodeDecodeError):
                            background += 1
                            continue
                        if not isinstance(reply, dict) or reply.get("messagetype") != kind or not isinstance(reply.get("client_data"), dict) or reply["client_data"].get("ref") != ref:
                            background += 1
                            continue
                        break
                    envelope = envelope_issue(reply, payload, cfg["USERNAME"])
                    if envelope:
                        record(kind, variant, envelope[0], started, envelope[1], background)
                    elif not contract["schemas"]:
                        record(kind, variant, "ACK_ONLY_NO_REFERENCE", started, "attachment has no device-info reference; not validated as equivalent", background)
                    elif "reply" not in reply:
                        record(kind, variant, "SCHEMA_MISMATCH", started, "reply field missing", background)
                    else:
                        differences = min((compare(form, reply["reply"]) for form in contract["schemas"]), key=len)
                        drift = fingerprint(reply["reply"]) not in contract["fingerprints"]
                        outcome = "SCHEMA_MISMATCH" if differences else "VALUE_CHANGED" if drift else "MATCH"
                        record(kind, variant, outcome, started, "; ".join(differences[:8]) if differences else "stable data differs from reference; review configuration changes" if drift else "structure and stable values match reference", background)
                except Exception as exc:
                    record(kind, variant, "ERROR", started, type(exc).__name__, background)
                    try:
                        ws.close(timeout=1)
                    except Exception:
                        pass
                    ws = None
        finally:
            if ws:
                try:
                    ws.close(timeout=1)
                except Exception:
                    pass
    print(f"Starting {2 * args.per_platform} sessions; {len(contracts)} reference steps per session. Output: {out}", flush=True)
    with ThreadPoolExecutor(max_workers=2 * args.per_platform) as pool:
        jobs = []
        for index in range(1, args.per_platform + 1):
            for platform in ("ios", "android"):
                jobs.append(pool.submit(worker, platform, index))
                time.sleep(1 / args.spawn_rate)
        for job in jobs:
            job.result()
    fields = ["session", "platform", "dummy_udid", "message_type", "variant", "outcome", "response_ms", "slow", "details", "background_messages"]
    csv_file(out / "validation.csv", rows, fields)
    counts = Counter(row["outcome"] for row in rows)
    summary = []
    for platform in ("ios", "android"):
        for kind in sorted({str(r["message_type"]) for r in rows}):
            selected = [r for r in rows if r["platform"] == platform and str(r["message_type"]) == kind]
            times = sorted(r["response_ms"] for r in selected if r["outcome"] != "NOT_RUN")
            summary.append(dict(platform=platform, message_type=kind, checks=len(selected),
                                outcomes=json.dumps(dict(Counter(r["outcome"] for r in selected))),
                                max_response_ms=max(times) if times else ""))
    csv_file(out / "message_summary.csv", summary, ["platform", "message_type", "checks", "outcomes", "max_response_ms"])
    (out / "README.txt").write_text(
        "One shared account; each platform label identifies its assigned simulated device, not separate startup APIs.\n"
        "Reference startup requests run sequentially once per session. This does not reproduce the desktop's parallel startup timing.\n"
        "Replies are matched by message type/reference; account and device identity are checked where applicable.\n"
        "MATCH checks required structure and a stable-value fingerprint; dynamic token/reference/time fields and list ordering are ignored.\n"
        "VALUE_CHANGED is not automatically an application defect; account configuration may have changed.\n"
        "No device-specific type-1 reference occurs in the supplied log. Its acknowledgment is explicitly not a full validation.\n"
        "Android fixtures remain exploratory. No USB actions, returned shell commands, software updates, or full hardware diagnostics are executed.\n"
        "No verified diagnostic start/final completion contract is available. Missing reference and unexecuted checks never count as MATCH.\n",
        encoding="utf-8")
    print(json.dumps(dict(counts), indent=2))
    print("CSV:", out / "validation.csv")
    return 1 if any(r["outcome"] in ("ERROR", "NOT_RUN", "ISOLATION_MISMATCH", "APPLICATION_FAILURE", "SCHEMA_MISMATCH", "VALUE_CHANGED") for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
