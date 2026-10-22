"""Selection-driven enterprise runner for reCheck360 desktop, backend and USB devices."""
from __future__ import annotations

import argparse
import ast
import base64
import csv
from datetime import datetime
import html
import json
from pathlib import Path
import re
import plistlib
import subprocess
import time
import uuid
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import requests
import websocket

from device_inventory import discover


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
NETWORK_CALLS: list[dict[str, Any]] = []
NETWORK_CALLS_LOCK = Lock()


def credentials() -> dict[str, str]:
    tree = ast.parse((WORKSPACE / "locustfile.py").read_text(encoding="utf-8-sig"))
    values = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and node.targets and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("USERNAME", "PASSWORD"):
                values[node.targets[0].id] = ast.literal_eval(node.value)
    if set(values) != {"USERNAME", "PASSWORD"}:
        raise RuntimeError("Staging credentials were not found in locustfile.py")
    return values


def row(module: str, group: str, test: str, status: str, started: float,
        details: str = "", evidence: str = "", blocker: str = "", device: str = "",
        sent: int = 0, received: int = 0) -> dict[str, Any]:
    return {
        "module": module,
        "group": group,
        "test": test,
        "status": status,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "device": device,
        "messages_sent": sent,
        "messages_received": received,
        "details": details,
        "blocker": blocker,
        "evidence": evidence,
    }


def process_ids(names: list[str]) -> list[int]:
    completed = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=15)
    lines = csv.reader(completed.stdout.splitlines())
    wanted = {name.lower().removesuffix(".exe") for name in names}
    return [int(parts[1]) for parts in lines if len(parts) > 1 and parts[0].lower().removesuffix(".exe") in wanted]


def desktop_window(desktop_map: dict[str, Any]):
    try:
        from pywinauto import Desktop  # type: ignore
    except ImportError:
        return None, "pywinauto is not installed; run install_enterprise_requirements.cmd"
    pids = process_ids(desktop_map["application"]["process_names"])
    if not pids:
        return None, "reCheck360 process is not running"
    try:
        windows = []
        for backend in (desktop_map["application"].get("automation_backend", "uia"), "win32"):
            for window in Desktop(backend=backend).windows():
                try:
                    title = window.window_text()
                    if (window.process_id() in pids and window.is_visible()
                            and ("recheck360" in title.lower() or backend != "win32")):
                        windows.append(window)
                except Exception:
                    continue
            if windows:
                break
        if not windows:
            return None, "reCheck360 has no UI Automation-visible window"
        windows.sort(key=lambda item: item.rectangle().width() * item.rectangle().height(), reverse=True)
        chosen = windows[0]
        try:
            bounds = chosen.rectangle()
            if chosen.is_minimized() or bounds.left < -10000 or bounds.top < -10000:
                import ctypes
                ctypes.windll.user32.ShowWindow(int(chosen.handle), 9)
                ctypes.windll.user32.SetForegroundWindow(int(chosen.handle))
                chosen.restore()
                time.sleep(0.7)
        except Exception:
            pass
        bounds = chosen.rectangle()
        if bounds.left < -10000 or bounds.top < -10000 or bounds.width() < 640 or bounds.height() < 400:
            return None, "reCheck360 window is minimized/off-screen and could not be restored"
        return chosen, ""
    except Exception as exc:
        return None, f"Desktop attachment failed: {type(exc).__name__}: {exc}"


def frontend_suite(selection: dict[str, Any], config: dict[str, Any], output: Path,
                   inventory: dict[str, Any]) -> list[dict[str, Any]]:
    selected = selection.get("frontend_pages", [])
    if not selected:
        return []
    mapping = json.loads((ROOT / config.get("desktop_map", "desktop_map.json")).read_text(encoding="utf-8-sig"))
    contract = json.loads((ROOT / "application_contract.json").read_text(encoding="utf-8-sig")) if (ROOT / "application_contract.json").is_file() else {"views": []}
    contract_views = {view["id"]: view for view in contract.get("views", [])}
    rows = []
    for page_id in selected:
        packaged = contract_views.get(page_id)
        if packaged:
            started = time.perf_counter()
            rows.append(row("Frontend", page_id, "Packaged JavaFX view contract", "PASS", started,
                            details=(f"{packaged['resource']} parsed; {packaged['control_count']} controls; "
                                     f"{len(packaged.get('actions', []))} declared actions"),
                            evidence=str(ROOT / "application_contract.json")))
    device_limit = int(selection.get("device_limit", config.get("maximum_real_devices", 20)))
    chosen_devices = inventory["devices"][:device_limit]
    if selection.get("require_devices") or "device_connection" in selected:
        if not chosen_devices:
            started = time.perf_counter()
            rows.append(row("Frontend", "Physical devices", "Discover selected USB devices", "BLOCKED", started,
                            blocker="No Android/iOS devices were returned by configured USB tools"))
        for device in chosen_devices:
            started = time.perf_counter()
            identity = device.get("udid") or device.get("serial_number")
            rows.append(row("Frontend", "Physical devices", "USB device available", "PASS", started,
                            details=f"{device['platform']} · {device.get('name','')} · {device.get('model','')}",
                            device=identity))
    started = time.perf_counter()
    window, attachment_error = desktop_window(mapping)
    rows.append(row("Frontend", "Application", "Attach to reCheck360 desktop window",
                    "PASS" if window else "BLOCKED", started,
                    "Desktop automation window attached" if window else "",
                    blocker=attachment_error))
    if not window:
        for page_id in selected:
            started = time.perf_counter()
            rows.append(row("Frontend", page_id, "Automated page workflow", "BLOCKED", started,
                            blocker=attachment_error))
        return rows

    try:
        window.set_focus()
    except Exception:
        pass
    page_map = mapping.get("pages", {})
    for page_id in selected:
        started = time.perf_counter()
        page = page_map.get(page_id)
        if not page and page_id in contract_views:
            source = contract_views[page_id]
            page = {"navigation": [source["name"]], "expected_text": source.get("expected_text", [])[:6]}
        evidence = output / "evidence" / f"frontend_{page_id}.png"
        evidence.parent.mkdir(exist_ok=True)
        if not page:
            rows.append(row("Frontend", page_id, "Automated page workflow", "BLOCKED", started,
                            blocker="No page entry exists in desktop_map.json"))
            continue
        try:
            navigated = page_id in ("login", "dashboard", "device_connection")
            clicked = ""
            for label in page.get("navigation", []):
                candidates = window.descendants(title_re=f"(?i)^{re.escape(label)}$")
                if candidates:
                    candidates[0].click_input()
                    clicked = label
                    navigated = True
                    time.sleep(0.35)
                    break
            texts = [str(control.window_text()).strip() for control in window.descendants()
                     if str(control.window_text()).strip()]
            expected = page.get("expected_text", [])
            found = [label for label in expected if any(label.lower() in text.lower() for text in texts)]
            screenshot_ok = False
            try:
                window.capture_as_image().save(evidence)
                evidence_value = str(evidence)
                screenshot_ok = True
            except Exception as exc:
                evidence_value = f"Screenshot unavailable: {type(exc).__name__}"
            if not texts and not screenshot_ok:
                rows.append(row("Frontend", page_id, "Navigate and validate page", "BLOCKED", started,
                                evidence=evidence_value,
                                blocker="JavaFX window is minimized/off-screen and exposes no UI Automation controls"))
                continue
            if not navigated:
                rows.append(row("Frontend", page_id, "Navigate and validate page", "BLOCKED", started,
                                details=f"Visible markers: {', '.join(found) or 'none'}",
                                evidence=evidence_value,
                                blocker="Navigation control was not exposed through Windows UI Automation; calibrate desktop_map.json"))
            elif not found:
                rows.append(row("Frontend", page_id, "Navigate and validate page", "FAIL", started,
                                details=f"Clicked: {clicked or 'current view'}; expected: {', '.join(expected)}",
                                evidence=evidence_value))
            else:
                details = f"Clicked: {clicked or 'current view'}; markers found: {', '.join(found)}"
                if page_id == "device_connection":
                    details += f"; USB devices discovered: {inventory['counts']['total']}"
                rows.append(row("Frontend", page_id, "Navigate and validate page", "PASS", started,
                                details=details, evidence=evidence_value))
        except Exception as exc:
            rows.append(row("Frontend", page_id, "Navigate and validate page", "ERROR", started,
                            blocker=f"{type(exc).__name__}: {exc}"))
    return rows


def receive(ws, message_type: int, ref: int, timeout: float):
    deadline = time.monotonic() + timeout
    background = 0
    while time.monotonic() < deadline:
        ws.settimeout(max(0.05, deadline - time.monotonic()))
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            break
        try:
            message = json.loads(raw)
        except Exception:
            background += 1
            continue
        if (isinstance(message, dict) and message.get("messagetype") == message_type
                and message.get("client_data", {}).get("ref") == ref):
            return message, background
        background += 1
    return None, background


def redact(value):
    if isinstance(value, dict):
        return {key: "[REDACTED]" if any(word in key.lower() for word in
                ("password", "token", "secret", "authorization")) else redact(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


LOG_HEADER = re.compile(
    r"^(?P<timestamp>\S+) \[(?P<user>[^]]+)] \[(?P<session>[^]]+)] \[(?P<platform>[^]]+)] "
    r"(?P<direction>Message sent|Received message):\s*$", re.MULTILINE
)


def load_message_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig")
    records: list[dict[str, Any]] = []
    headers = list(LOG_HEADER.finditer(text))
    for index, match in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        block = text[match.end():end]
        start = block.find("{")
        if start < 0:
            continue
        try:
            payload = json.JSONDecoder().raw_decode(block[start:])[0]
        except (json.JSONDecodeError, ValueError):
            continue
        records.append({"direction": "SENT" if match.group("direction") == "Message sent" else "RECEIVED",
                        "timestamp": match.group("timestamp"), "user": match.group("user"),
                        "session": match.group("session"), "platform": match.group("platform"),
                        "payload": payload})
    if records:
        return records
    payloads: list[dict[str, Any]] = []
    try:
        raw = json.loads(text)
        if isinstance(raw, list):
            payloads = raw
        elif isinstance(raw, dict):
            payloads.extend(raw.get("payloads", raw.get("requests", raw.get("session_requests", []))))
            for device in raw.get("devices", []):
                payloads.extend(device.get("requests", []))
    except json.JSONDecodeError:
        for line in text.splitlines():
            marker = None
            if "Message sent" in line:
                marker = line.find("{", line.find("Message sent"))
            elif line.lstrip().startswith("{"):
                marker = line.find("{")
            if marker is None or marker < 0:
                continue
            try:
                payloads.append(json.JSONDecoder().raw_decode(line[marker:])[0])
            except (json.JSONDecodeError, ValueError):
                continue
    return [{"direction": "SENT" if "status" not in item else "RECEIVED", "timestamp": "",
             "user": "", "session": item.get("device_name", "SESSION"),
             "platform": item.get("device_operating_system", ""), "payload": item}
            for item in payloads if isinstance(item, dict) and isinstance(item.get("messagetype"), int)]


def load_payloads(path: Path) -> list[dict[str, Any]]:
    return [record["payload"] for record in load_message_records(path)
            if record["direction"] == "SENT" and "status" not in record["payload"]]


def record_network_call(*, transport: str, method: str, endpoint: str, operation: str,
                        started: float, result: str, request_body: Any = None,
                        response_body: Any = None, status_code: Any = "", device: str = "",
                        message_type: Any = "", ref: Any = "", error: str = "") -> None:
    response_status = response_body.get("status", "") if isinstance(response_body, dict) else ""
    item = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "transport": transport,
        "method": method,
        "endpoint": endpoint,
        "operation": operation,
        "device": device,
        "message_type": message_type,
        "ref": ref,
        "result": result,
        "status_code": status_code,
        "response_status": response_status,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "request_json": json.dumps(redact(request_body), ensure_ascii=False) if request_body is not None else "",
        "response_json": json.dumps(redact(response_body), ensure_ascii=False) if response_body is not None else "",
        "error": error,
    }
    with NETWORK_CALLS_LOCK:
        NETWORK_CALLS.append(item)


def login_token(config: dict[str, Any], timeout: float):
    auth = credentials()
    request_body = {"username": auth["USERNAME"], "password": auth["PASSWORD"]}
    started = time.perf_counter()
    try:
        response = requests.post(config["login_url"], json=request_body, timeout=timeout, allow_redirects=False)
    except Exception as exc:
        record_network_call(transport="HTTP", method="POST", endpoint=config["login_url"],
                            operation="Authentication", started=started, result="ERROR",
                            request_body=request_body, error=f"{type(exc).__name__}: {exc}")
        raise
    body = response.json() if response.content else {}
    nested = body.get("data") or {}
    token = body.get("token") or body.get("access_token") or nested.get("token") or nested.get("access_token")
    result = "PASS" if response.status_code == 200 and token else "FAIL"
    record_network_call(transport="HTTP", method="POST", endpoint=config["login_url"],
                        operation="Authentication", started=started, result=result,
                        request_body=request_body, response_body=body, status_code=response.status_code)
    if response.status_code != 200 or not token:
        raise RuntimeError(f"Authentication failed: HTTP {response.status_code}")
    return token


def server_status_check(config: dict[str, Any], timeout: float) -> dict[str, Any]:
    """Record the staging health endpoint in every backend-oriented report."""
    endpoint = config.get("server_status_url", "https://staging.phone-diagnostics.com/v1/ServerStatus")
    started = time.perf_counter()
    try:
        response = requests.get(endpoint, timeout=timeout, allow_redirects=False)
        body = response.json() if response.content else {}
        status_text = body.get("status", "") if isinstance(body, dict) else ""
        passed = response.status_code == 200
        record_network_call(transport="HTTP", method="GET", endpoint=endpoint,
                            operation="Server status", started=started,
                            result="PASS" if passed else "FAIL", response_body=body,
                            status_code=response.status_code)
        return row("Backend", "Server health", "Staging server status",
                   "PASS" if passed else "FAIL", started,
                   f"HTTP {response.status_code}; {status_text or 'no status message'}")
    except Exception as exc:
        record_network_call(transport="HTTP", method="GET", endpoint=endpoint,
                            operation="Server status", started=started, result="ERROR",
                            error=f"{type(exc).__name__}: {exc}")
        return row("Backend", "Server health", "Staging server status", "ERROR", started,
                   blocker=f"{type(exc).__name__}: {exc}")


def message_event(direction: str, payload: dict[str, Any], started: float, device_type: str,
                  metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = metadata or {}
    return {
        "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "source_timestamp": metadata.get("timestamp", ""),
        "direction": direction,
        "user": metadata.get("user", ""),
        "session": metadata.get("session", payload.get("device_name", "SESSION")),
        "device_type": metadata.get("platform", device_type) or device_type,
        "device_name": metadata.get("session", payload.get("device_name", "")),
        "udid": payload.get("udid", ""),
        "message_type": payload.get("messagetype", ""),
        "ref": payload.get("client_data", {}).get("ref", ""),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "json": json.dumps(redact(payload), ensure_ascii=False),
    }


def message_suite(selection: dict[str, Any], config: dict[str, Any], allowed_udids: set[str] | None = None):
    rows, events = [], []
    fixed_protocol = bool(selection.get("fixed_protocol"))
    source_value = str(selection.get("payload_file", "")).strip()
    source = Path(source_value) if source_value else ROOT / "fixed_ios_8_messages.json"
    timeout = float(selection.get("timeout_seconds", 40))
    if not source.is_file():
        started = time.perf_counter()
        rows.append(row("Messages", "Input", "Load payload file", "BLOCKED", started,
                        blocker="Select an existing JSON or application log file"))
        return rows, events
    try:
        records = [record for record in load_message_records(source)
                   if record["direction"] == "SENT" and "status" not in record["payload"]
                   and isinstance(record["payload"].get("messagetype"), int)]
    except Exception as exc:
        started = time.perf_counter()
        rows.append(row("Messages", "Input", "Load payload file", "ERROR", started,
                        blocker=f"{type(exc).__name__}: {exc}"))
        return rows, events
    if allowed_udids is not None:
        records = [record for record in records if record["payload"].get("udid") in allowed_udids]
    fixed_names = {
        1: "Device connect",
        2: "Device information result",
        3: "Battery command request",
        4: "Battery result",
        5: "OEM command request",
        6: "OEM result",
        7: "Validation command request",
        8: "Validation result",
    }
    if fixed_protocol:
        by_type = {record["payload"].get("messagetype"): record for record in records
                   if record["payload"].get("messagetype") in fixed_names}
        missing = [message_type for message_type in fixed_names if message_type not in by_type]
        if missing:
            started = time.perf_counter()
            rows.append(row("Messages", "Fixed iOS protocol", "Validate eight-message profile", "BLOCKED", started,
                            blocker=f"Missing fixed message types: {missing}"))
            return rows, events
        records = [by_type[message_type] for message_type in fixed_names]
    records = records[:max(1, min(500, int(selection.get("max_messages", 100))))]
    if not records:
        started = time.perf_counter()
        rows.append(row("Messages", "Input", "Load payload file", "BLOCKED", started,
                        blocker="No outgoing payloads matched the selected mode/devices"))
        return rows, events
    ws = None
    try:
        token = login_token(config, timeout)
        ws = websocket.create_connection(config["ws_url"], header={"Authorization": "Bearer " + token}, timeout=timeout)
        for number, record in enumerate(records, 1):
            original = record["payload"]
            payload = json.loads(json.dumps(original))
            ref = uuid.uuid4().int >> 76
            payload["client_data"] = {"ref": ref}
            platform = "ios" if fixed_protocol else str(payload.get("device_operating_system", "session")).lower()
            started = time.perf_counter()
            ws.send(json.dumps(payload))
            events.append(message_event("SENT", payload, started, platform, record))
            reply, background = receive(ws, payload["messagetype"], ref, timeout)
            test_name = (f"{number}/8 - type {payload['messagetype']} - {fixed_names[payload['messagetype']]}"
                         if fixed_protocol else f"Message {number} - type {payload['messagetype']}")
            test_group = "Fixed iOS protocol" if fixed_protocol else platform
            if reply is None:
                record_network_call(transport="WebSocket", method="SEND", endpoint=config["ws_url"],
                                    operation=fixed_names.get(payload["messagetype"], f"Message type {payload['messagetype']}"),
                                    started=started, result="TIMEOUT", request_body=payload,
                                    device=payload.get("udid", ""), message_type=payload["messagetype"], ref=ref,
                                    error=f"No exact response within {timeout}s; background={background}")
            if reply is None and fixed_protocol:
                rows.append(row("Messages", test_group, test_name, "TIMEOUT", started,
                                f"Unmatched/background messages: {background}",
                                blocker=f"No exact message_type + ref response within {timeout}s",
                                device=payload.get("udid", ""), sent=1))
                continue
            if reply is None:
                rows.append(row("Messages", platform, f"Message {number} · type {payload['messagetype']}",
                                "TIMEOUT", started, f"Unmatched/background messages: {background}",
                                blocker=f"No exact message_type + ref response within {timeout}s",
                                device=payload.get("udid", ""), sent=1))
                continue
            events.append(message_event("RECEIVED", reply, started, platform, record))
            udid_match = not payload.get("udid") or reply.get("udid", payload.get("udid")) == payload.get("udid")
            success = reply.get("status") == "success" and udid_match
            record_network_call(transport="WebSocket", method="SEND", endpoint=config["ws_url"],
                                operation=fixed_names.get(payload["messagetype"], f"Message type {payload['messagetype']}"),
                                started=started, result="PASS" if success else "FAIL", request_body=payload,
                                response_body=reply, device=payload.get("udid", ""),
                                message_type=payload["messagetype"], ref=ref)
            if fixed_protocol:
                rows.append(row("Messages", test_group, test_name, "PASS" if success else "FAIL", started,
                                f"status={reply.get('status')}; type_match=true; ref_match=true; "
                                f"udid_match={str(udid_match).lower()}",
                                device=payload.get("udid", ""), sent=1, received=1))
                continue
            rows.append(row("Messages", platform, f"Message {number} · type {payload['messagetype']}",
                            "PASS" if success else "FAIL", started,
                            f"status={reply.get('status')}; type_match=true; ref_match=true; udid_match={str(udid_match).lower()}",
                            device=payload.get("udid", ""), sent=1, received=1))
    except Exception as exc:
        started = time.perf_counter()
        rows.append(row("Messages", "Connection", "Staging message session", "ERROR", started,
                        blocker=f"{type(exc).__name__}: {exc}"))
    finally:
        if ws:
            try:
                ws.close(timeout=1)
            except Exception:
                pass
    return rows, events


FIXED_MESSAGE_NAMES = {
    1: "Device connect",
    2: "Device information result",
    3: "Battery command request",
    4: "Battery result",
    5: "OEM command request",
    6: "OEM result",
    7: "Validation command request",
    8: "Validation result",
}


def deep_replace(value: Any, old: str, new: str) -> Any:
    if isinstance(value, dict):
        return {key: deep_replace(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [deep_replace(item, old, new) for item in value]
    if isinstance(value, str):
        return value.replace(old, new)
    return value


def fixed_device_payloads(device_number: int) -> tuple[str, str, list[dict[str, Any]]]:
    templates = load_payloads(ROOT / "fixed_ios_8_messages.json")
    by_type = {item.get("messagetype"): item for item in templates if item.get("messagetype") in FIXED_MESSAGE_NAMES}
    if sorted(by_type) != list(FIXED_MESSAGE_NAMES):
        raise RuntimeError("The fixed iOS profile must contain message types 1 through 8")
    old_udid = str(by_type[1].get("udid", ""))
    udid = f"00008110-{device_number:016X}"
    device_name = f"Load iPhone {device_number:02d}"
    payloads = [deep_replace(json.loads(json.dumps(by_type[message_type])), old_udid, udid)
                for message_type in FIXED_MESSAGE_NAMES]
    connect = payloads[0]
    try:
        info = plistlib.loads(base64.b64decode(connect["device_info"]))
        info["UniqueDeviceID"] = udid
        info["SerialNumber"] = f"QAIOS{device_number:07d}"
        info["DeviceName"] = device_name
        connect["device_info"] = base64.b64encode(plistlib.dumps(info, fmt=plistlib.FMT_XML)).decode()
    except Exception as exc:
        raise RuntimeError(f"Unable to build device {device_number} fixture: {exc}") from exc
    return device_name, udid, payloads


def fixed_batch_suite(selection: dict[str, Any], config: dict[str, Any]):
    timeout = float(selection.get("timeout_seconds", 40))
    rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    event_lock = Lock()
    try:
        token = login_token(config, timeout)
    except Exception as exc:
        started = time.perf_counter()
        return [row("Fixed protocol load", "Authentication", "Staging login", "ERROR", started,
                    blocker=f"{type(exc).__name__}: {exc}")], events

    def worker(device_number: int, batch_number: int):
        local_rows: list[dict[str, Any]] = []
        local_events: list[dict[str, Any]] = []
        completed: set[int] = set()
        device_name, udid, payloads = fixed_device_payloads(device_number)
        group = f"Batch {batch_number} - devices {(batch_number - 1) * 5 + 1}-{batch_number * 5}"
        metadata = {"user": "staging-shared", "session": device_name, "platform": "iOS"}
        ws = None
        try:
            ws = websocket.create_connection(config["ws_url"], header={"Authorization": "Bearer " + token},
                                             timeout=timeout)
            for sequence, payload in enumerate(payloads, 1):
                message_type = payload["messagetype"]
                ref = uuid.uuid4().int >> 76
                payload["client_data"] = {"ref": ref}
                started = time.perf_counter()
                ws.send(json.dumps(payload))
                local_events.append(message_event("SENT", payload, started, "ios", metadata))
                reply, background = receive(ws, message_type, ref, timeout)
                test_name = f"{device_name} - {sequence}/8 - type {message_type} - {FIXED_MESSAGE_NAMES[message_type]}"
                if reply is None:
                    record_network_call(transport="WebSocket", method="SEND", endpoint=config["ws_url"],
                                        operation=FIXED_MESSAGE_NAMES[message_type], started=started,
                                        result="TIMEOUT", request_body=payload, device=udid,
                                        message_type=message_type, ref=ref,
                                        error=f"No exact response within {timeout}s; background={background}")
                    local_rows.append(row("Fixed protocol load", group, test_name, "TIMEOUT", started,
                                          f"device={device_name}; platform=iOS; batch={batch_number}",
                                          blocker=f"No exact type + ref response within {timeout}s",
                                          device=udid, sent=1))
                    completed.add(message_type)
                    continue
                local_events.append(message_event("RECEIVED", reply, started, "ios", metadata))
                udid_match = reply.get("udid", udid) == udid
                success = reply.get("status") == "success" and udid_match
                record_network_call(transport="WebSocket", method="SEND", endpoint=config["ws_url"],
                                    operation=FIXED_MESSAGE_NAMES[message_type], started=started,
                                    result="PASS" if success else "FAIL", request_body=payload,
                                    response_body=reply, device=udid, message_type=message_type, ref=ref)
                local_rows.append(row("Fixed protocol load", group, test_name,
                                      "PASS" if success else "FAIL", started,
                                      f"device={device_name}; platform=iOS; batch={batch_number}; "
                                      f"status={reply.get('status')}; type_match=true; ref_match=true; "
                                      f"udid_match={str(udid_match).lower()}",
                                      device=udid, sent=1, received=1))
                completed.add(message_type)
        except Exception as exc:
            for message_type in FIXED_MESSAGE_NAMES:
                if message_type not in completed:
                    started = time.perf_counter()
                    local_rows.append(row("Fixed protocol load", group,
                                          f"{device_name} - type {message_type} - {FIXED_MESSAGE_NAMES[message_type]}",
                                          "ERROR", started, f"device={device_name}; platform=iOS; batch={batch_number}",
                                          blocker=f"{type(exc).__name__}: {exc}", device=udid))
        finally:
            if ws:
                try:
                    ws.close(timeout=1)
                except Exception:
                    pass
        with event_lock:
            events.extend(local_events)
        return device_number, local_rows

    for batch_number, device_numbers in enumerate((range(1, 6), range(6, 11), range(11, 16)), 1):
        batch_results = []
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(worker, device_number, batch_number) for device_number in device_numbers]
            for future in as_completed(futures):
                batch_results.append(future.result())
        for _, device_rows in sorted(batch_results):
            rows.extend(device_rows)
    return rows, events


def dummy_fixture(platform: str, number: int, run_id: str) -> dict[str, Any]:
    identity = uuid.uuid5(uuid.NAMESPACE_URL, f"recheck-harness/{run_id}/{platform}/{number}").hex
    if platform == "ios":
        udid = identity[:8].upper() + "-" + identity[8:24].upper()
        info = {"UniqueDeviceID": udid, "SerialNumber": "QA" + identity[:10].upper(),
                "DeviceName": f"Dummy iPhone {number}", "DeviceClass": "iPhone",
                "ProductType": "iPhone13,1", "ProductVersion": "18.0"}
        encoded = plistlib.dumps(info, fmt=plistlib.FMT_XML)
    else:
        udid = "QAANDROID" + identity[:12].upper()
        info = {"serial": udid, "manufacturer": "QA", "model": f"Dummy Android {number}",
                "android_version": "14"}
        encoded = json.dumps(info).encode()
    return {"client_data": {"ref": 1}, "messagetype": 1, "udid": udid,
            "device_name": info.get("DeviceName", info.get("model", "")),
            "device_operating_system": platform, "operating_system": "windows",
            "device_info": base64.b64encode(encoded).decode()}


def dummy_suite(selection: dict[str, Any], config: dict[str, Any]):
    ios_count = int(selection.get("dummy_ios", 0))
    android_count = int(selection.get("dummy_android", 0))
    rounds = max(1, min(20, int(selection.get("rounds", 1))))
    timeout = float(selection.get("timeout_seconds", 40))
    run_id = datetime.now().strftime("%Y%m%d%H%M%S")
    fixtures = ([dummy_fixture("ios", index, run_id) for index in range(1, ios_count + 1)] +
                [dummy_fixture("android", index, run_id) for index in range(1, android_count + 1)])
    rows, events = [], []
    lock = __import__("threading").Lock()
    try:
        token = login_token(config, timeout)
    except Exception as exc:
        started = time.perf_counter()
        return [row("Dummy devices", "Authentication", "Login API", "ERROR", started,
                    blocker=f"{type(exc).__name__}: {exc}")], events

    def worker(payload):
        local_rows, local_events = [], []
        ws = None
        try:
            ws = websocket.create_connection(config["ws_url"], header={"Authorization": "Bearer " + token}, timeout=timeout)
            for current_round in range(1, rounds + 1):
                request = json.loads(json.dumps(payload))
                request["client_data"] = {"ref": uuid.uuid4().int >> 76}
                started = time.perf_counter()
                ws.send(json.dumps(request))
                local_events.append(message_event("SENT", request, started, request["device_operating_system"]))
                reply, background = receive(ws, 1, request["client_data"]["ref"], timeout)
                if reply is None:
                    record_network_call(transport="WebSocket", method="SEND", endpoint=config["ws_url"],
                                        operation="Dummy device connect", started=started, result="TIMEOUT",
                                        request_body=request, device=request["udid"], message_type=1,
                                        ref=request["client_data"]["ref"],
                                        error=f"No exact response within {timeout}s; background={background}")
                    local_rows.append(row("Dummy devices", request["device_operating_system"],
                                          f"{request['device_name']} · round {current_round}", "TIMEOUT", started,
                                          f"Background messages: {background}", blocker=f"No exact response within {timeout}s",
                                          device=request["udid"], sent=1))
                    break
                local_events.append(message_event("RECEIVED", reply, started, request["device_operating_system"]))
                exact = (reply.get("messagetype") == 1 and reply.get("client_data", {}).get("ref") == request["client_data"]["ref"]
                         and reply.get("udid") == request["udid"])
                acknowledged = exact and reply.get("status") == "success"
                record_network_call(transport="WebSocket", method="SEND", endpoint=config["ws_url"],
                                    operation="Dummy device connect", started=started,
                                    result="PASS" if acknowledged else "FAIL", request_body=request,
                                    response_body=reply, device=request["udid"], message_type=1,
                                    ref=request["client_data"]["ref"])
                local_rows.append(row("Dummy devices", request["device_operating_system"],
                                      f"{request['device_name']} · round {current_round}",
                                      "ACKNOWLEDGED" if acknowledged else "REJECTED", started,
                                      "Backend acknowledged synthetic payload; physical hardware was not tested",
                                      device=request["udid"], sent=1, received=1))
                if not acknowledged:
                    break
        except Exception as exc:
            started = time.perf_counter()
            local_rows.append(row("Dummy devices", payload["device_operating_system"], payload["device_name"],
                                  "ERROR", started, blocker=f"{type(exc).__name__}: {exc}", device=payload["udid"]))
        finally:
            if ws:
                try:
                    ws.close(timeout=1)
                except Exception:
                    pass
        with lock:
            events.extend(local_events)
        return local_rows

    with ThreadPoolExecutor(max_workers=max(1, min(len(fixtures), 20))) as pool:
        for device_rows in pool.map(worker, fixtures):
            rows.extend(device_rows)
    return rows, events


def real_device_suite(selection: dict[str, Any], config: dict[str, Any], inventory: dict[str, Any]):
    rows, events = [], []
    required = max(1, min(20, int(selection.get("real_device_count", 20))))
    selected_udids = {str(item) for item in selection.get("selected_udids", []) if str(item)}
    available_devices = inventory["devices"]
    if selected_udids:
        available_devices = [device for device in available_devices
                             if device.get("udid", device.get("serial_number", "")) in selected_udids]
    devices = available_devices[:required]
    for device in devices:
        started = time.perf_counter()
        rows.append(row("Real devices", device["platform"], device.get("name", "Physical device"), "CONNECTED", started,
                        f"Detected by bundled USB tool; model={device.get('model','')}; state={device.get('state','')}",
                        device=device.get("udid", device.get("serial_number", ""))))
    if len(devices) < required:
        started = time.perf_counter()
        rows.append(row("Real devices", "USB inventory", f"Required physical devices: {required}", "BLOCKED", started,
                        details=f"Detected {len(devices)}", blocker=f"Connect {required - len(devices)} more physical device(s)"))
    if selection.get("payload_file") and devices:
        message_rows, events = message_suite(selection, config, {device.get("udid", "") for device in devices})
        for item in message_rows:
            item["module"] = "Real devices"
        rows.extend(message_rows)
    return rows, events


def load_session(index: int, config: dict[str, Any], token: str, timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    ws = None
    try:
        ws = websocket.create_connection(config["ws_url"], header={"Authorization": "Bearer " + token}, timeout=timeout)
        ref = uuid.uuid4().int >> 76
        payload = {"messagetype": 119, "client_data": {"ref": ref}, "app_version": "1.7.7",
                   "operating_system": "windows", "architecture": "x64"}
        ws.send(json.dumps(payload))
        reply, background = receive(ws, 119, ref, timeout)
        if reply is None:
            return row("Backend", "Concurrent load", f"Session {index:03d}", "TIMEOUT", started,
                       f"Background messages: {background}", blocker=f"No correlated reply within {timeout}s", sent=1)
        status = "PASS" if reply.get("status") == "success" else "FAIL"
        return row("Backend", "Concurrent load", f"Session {index:03d}", status, started,
                   f"status={reply.get('status')}; ref={ref}; background={background}", sent=1, received=1)
    except Exception as exc:
        return row("Backend", "Concurrent load", f"Session {index:03d}", "ERROR", started,
                   blocker=f"{type(exc).__name__}: {exc}")
    finally:
        if ws:
            try:
                ws.close(timeout=1)
            except Exception:
                pass


def backend_suite(selection: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    selected = set(selection.get("backend_features", []))
    if not selected:
        return []
    rows = []
    timeout = float(selection.get("timeout_seconds", config.get("response_timeout_seconds", 40)))
    token = None
    if selected:
        started = time.perf_counter()
        try:
            auth = credentials()
            response = requests.post(config["login_url"], json={"username": auth["USERNAME"], "password": auth["PASSWORD"]},
                                     timeout=timeout, allow_redirects=False)
            body = response.json() if response.content else {}
            nested = body.get("data") or {}
            token = body.get("token") or body.get("access_token") or nested.get("token") or nested.get("access_token")
            status = "PASS" if response.status_code == 200 and token else "FAIL"
            rows.append(row("Backend", "Authentication", "Login API", status, started,
                            f"HTTP {response.status_code}; token present: {bool(token)}"))
        except Exception as exc:
            rows.append(row("Backend", "Authentication", "Login API", "ERROR", started,
                            blocker=f"{type(exc).__name__}: {exc}"))
    if not token:
        for feature in selected - {"authentication"}:
            started = time.perf_counter()
            rows.append(row("Backend", feature, "Backend feature", "BLOCKED", started,
                            blocker="Authentication did not provide a token"))
        return rows
    if selected == {"authentication"}:
        return rows

    if "load" in selected:
        users = int(selection.get("users", 1))
        with ThreadPoolExecutor(max_workers=min(users, 50)) as pool:
            futures = [pool.submit(load_session, index, config, token, timeout) for index in range(1, users + 1)]
            for future in as_completed(futures):
                rows.append(future.result())

    ws = None
    started = time.perf_counter()
    try:
        ws = websocket.create_connection(config["ws_url"], header={"Authorization": "Bearer " + token}, timeout=timeout)
        rows.append(row("Backend", "WebSocket", "Authenticated connection", "PASS", started,
                        "Connection opened"))
        if "version_contract" in selected or "websocket_connection" in selected:
            ref = uuid.uuid4().int >> 76
            payload = {"messagetype": 119, "client_data": {"ref": ref}, "app_version": "1.7.7",
                       "operating_system": "windows", "architecture": "x64"}
            started = time.perf_counter()
            ws.send(json.dumps(payload))
            reply, background = receive(ws, 119, ref, timeout)
            if reply is None:
                rows.append(row("Backend", "Version", "Message type 119 correlation", "TIMEOUT", started,
                                f"Background messages: {background}", blocker=f"No correlated reply within {timeout}s", sent=1))
            else:
                ok = reply.get("status") == "success"
                rows.append(row("Backend", "Version", "Message type 119 correlation", "PASS" if ok else "FAIL", started,
                                f"Status: {reply.get('status')}; ref: {ref}; background messages: {background}", sent=1, received=1))

        payload_features = selected & {"device_registration", "battery", "diagnostics", "message_correlation"}
        if payload_features:
            payload_path = Path(str(selection.get("payload_file", "")))
            if not payload_path.is_file():
                for feature in sorted(payload_features):
                    started = time.perf_counter()
                    rows.append(row("Backend", feature, "Real-device payload contract", "BLOCKED", started,
                                    blocker="Select an existing captured payload JSON file; synthetic data is not used for a real-device pass"))
            else:
                raw = json.loads(payload_path.read_text(encoding="utf-8-sig"))
                payloads = raw if isinstance(raw, list) else raw.get("payloads", raw.get("requests", []))
                if not payloads and isinstance(raw, dict) and raw.get("devices"):
                    payloads = [request for device in raw["devices"] for request in device.get("requests", [])]
                payloads = payloads[:max(1, int(selection.get("device_limit", 20))) * 20]
                wanted = {1} if "device_registration" in payload_features else set()
                if "battery" in payload_features: wanted.update((3, 4))
                if "diagnostics" in payload_features: wanted.update((5, 6, 7, 8))
                for source in [item for item in payloads if item.get("messagetype") in wanted]:
                    payload = json.loads(json.dumps(source))
                    ref = uuid.uuid4().int >> 76
                    payload["client_data"] = {"ref": ref}
                    started = time.perf_counter()
                    ws.send(json.dumps(payload))
                    reply, background = receive(ws, payload["messagetype"], ref, timeout)
                    device = payload.get("udid", "")
                    if reply is None:
                        rows.append(row("Backend", "Payload", f"Message type {payload['messagetype']}", "TIMEOUT", started,
                                        f"Background messages: {background}", blocker=f"No correlated reply within {timeout}s",
                                        device=device, sent=1))
                    else:
                        matched = not device or reply.get("udid", device) == device
                        rows.append(row("Backend", "Payload", f"Message type {payload['messagetype']}",
                                        "PASS" if matched and reply.get("status") == "success" else "FAIL", started,
                                        f"status={reply.get('status')}; identity_match={matched}; background={background}",
                                        device=device, sent=1, received=1))
    except Exception as exc:
        rows.append(row("Backend", "WebSocket", "Connection or execution", "ERROR", started,
                        blocker=f"{type(exc).__name__}: {exc}"))
    finally:
        if ws:
            try: ws.close(timeout=1)
            except Exception: pass
    return rows


def write_report(output: Path, selection: dict[str, Any], inventory: dict[str, Any], rows: list[dict[str, Any]],
                 started: datetime, events: list[dict[str, Any]] | None = None):
    events = events or []
    finished = datetime.now().astimezone()
    summary = {
        "tests": len(rows),
        "pass": sum(r["status"] == "PASS" for r in rows),
        "fail": sum(r["status"] in ("FAIL", "ERROR", "TIMEOUT", "REJECTED") for r in rows),
        "blocked": sum(r["status"] == "BLOCKED" for r in rows),
        "acknowledged": sum(r["status"] == "ACKNOWLEDGED" for r in rows),
        "connected": sum(r["status"] == "CONNECTED" for r in rows),
        "messages_sent": (sum(event["direction"] == "SENT" for event in events)
                          if events else sum(r["messages_sent"] for r in rows)),
        "messages_received": (sum(event["direction"] == "RECEIVED" for event in events)
                               if events else sum(r["messages_received"] for r in rows)),
        "api_calls": len(NETWORK_CALLS),
        "api_pass": sum(call["result"] == "PASS" for call in NETWORK_CALLS),
        "api_fail": sum(call["result"] in ("FAIL", "ERROR", "TIMEOUT") for call in NETWORK_CALLS),
        "duration_ms": round((finished - started).total_seconds() * 1000, 2),
        "real_devices": inventory["counts"],
    }
    summary["verification_scope"] = {
        "messages": "Exact type + reference + status + UDID correlation",
        "fixed_batch": "15 synthetic iOS devices in sequential batches of five; eight exact protocol messages per device",
        "dummy": "Synthetic backend acknowledgment only; no hardware verification",
        "real": "Physical USB identity; payload contract only when a matching connected UDID is supplied",
        "desktop": "Packaged view contract plus live Windows UI checks",
    }.get(selection.get("mode"), "Combined suite")
    batch_summary: list[dict[str, Any]] = []
    device_summary: list[dict[str, Any]] = []
    if selection.get("mode") == "fixed_batch":
        for batch_number in range(1, 4):
            prefix = f"Batch {batch_number} -"
            batch_rows = [item for item in rows if item["group"].startswith(prefix)]
            batch_summary.append({
                "batch": batch_number,
                "device_range": f"{(batch_number - 1) * 5 + 1}-{batch_number * 5}",
                "devices": len({item["device"] for item in batch_rows}),
                "tests": len(batch_rows),
                "pass": sum(item["status"] == "PASS" for item in batch_rows),
                "fail": sum(item["status"] != "PASS" for item in batch_rows),
                "messages_sent": sum(item["messages_sent"] for item in batch_rows),
                "messages_received": sum(item["messages_received"] for item in batch_rows),
                "message_duration_ms": round(sum(float(item["duration_ms"]) for item in batch_rows), 2),
            })
        for device_number in range(1, 16):
            device_name = f"Load iPhone {device_number:02d}"
            udid = f"00008110-{device_number:016X}"
            device_rows = [item for item in rows if item["device"] == udid]
            device_summary.append({
                "device_number": device_number,
                "device_name": device_name,
                "platform": "iOS",
                "udid": udid,
                "batch": (device_number - 1) // 5 + 1,
                "tests": len(device_rows),
                "pass": sum(item["status"] == "PASS" for item in device_rows),
                "fail": sum(item["status"] != "PASS" for item in device_rows),
                "messages_sent": sum(item["messages_sent"] for item in device_rows),
                "messages_received": sum(item["messages_received"] for item in device_rows),
                "message_duration_ms": round(sum(float(item["duration_ms"]) for item in device_rows), 2),
            })
    document = {"environment": "staging", "started_at": started.isoformat(timespec="seconds"),
                "finished_at": finished.isoformat(timespec="seconds"), "selection": selection,
                "mode": selection.get("mode", "combined"), "device_inventory": inventory,
                 "summary": summary, "results": rows,
                 "sent_messages": [event for event in events if event["direction"] == "SENT"],
                 "received_messages": [event for event in events if event["direction"] == "RECEIVED"],
                 "api_calls": list(NETWORK_CALLS), "batch_summary": batch_summary,
                 "device_summary": device_summary}
    (output / "results.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    with (output / "results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["module", "status"])
        writer.writeheader(); writer.writerows(rows)
    message_fields = ["timestamp", "source_timestamp", "direction", "user", "session", "device_type",
                      "device_name", "udid", "message_type", "ref", "duration_ms", "json"]
    for direction, filename in (("SENT", "messages_sent.csv"), ("RECEIVED", "messages_received.csv")):
        with (output / filename).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=message_fields)
            writer.writeheader()
            writer.writerows(event for event in events if event["direction"] == direction)
    api_fields = ["timestamp", "transport", "method", "endpoint", "operation", "device", "message_type",
                  "ref", "result", "status_code", "response_status", "duration_ms", "request_json",
                  "response_json", "error"]
    with (output / "api_calls.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=api_fields)
        writer.writeheader(); writer.writerows(NETWORK_CALLS)
    for filename, summary_rows in (("batch_summary.csv", batch_summary), ("device_summary.csv", device_summary)):
        with (output / filename).open("w", encoding="utf-8-sig", newline="") as handle:
            fields = list(summary_rows[0]) if summary_rows else ["status"]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader(); writer.writerows(summary_rows)
    readable = []
    for event in events:
        label = "Message sent" if event["direction"] == "SENT" else "Received message"
        timestamp = event["timestamp"]
        user = event.get("user") or "user"
        session = event.get("session") or "SESSION"
        platform = event.get("device_type") or "UNKNOWN"
        try:
            body = json.dumps(json.loads(event["json"]), indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            body = event["json"]
        readable.append(f"{timestamp} [{user}] [{session}] [{platform}] {label}:\n{body}\n")
    (output / "messages_readable.log").write_text("\n".join(readable), encoding="utf-8")
    cards = "".join(f"<div class=card><small>{html.escape(k.replace('_',' ').title())}</small><b>{html.escape(str(v))}</b></div>"
                    for k, v in summary.items() if k != "real_devices")
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(r[k]))}</td>" for k in
                   ("module", "group", "test", "status", "duration_ms", "device", "messages_sent", "messages_received", "details", "blocker")) + "</tr>" for r in rows)
    page = f"""<!doctype html><meta charset=utf-8><title>reCheck360 Enterprise QA</title><style>
body{{font:14px Segoe UI;margin:0;background:#f3f6fa;color:#182230}}header{{background:#17365d;color:white;padding:24px}}main{{padding:24px}}.cards{{display:flex;gap:10px;flex-wrap:wrap}}.card{{background:white;padding:14px;border-radius:9px;min-width:130px;border:1px solid #d8e0ea}}.card small,.card b{{display:block}}.card b{{font-size:22px;margin-top:5px}}table{{width:100%;border-collapse:collapse;background:white;margin-top:20px}}th{{background:#17365d;color:white}}th,td{{padding:8px;border:1px solid #d8e0ea;vertical-align:top}}tr:nth-child(even){{background:#f8fafc}}</style>
<header><h1>reCheck360 Enterprise QA Report</h1><div>Staging · {started.isoformat(timespec='seconds')} · {inventory['counts']['total']} real devices</div></header><main><div class=cards>{cards}</div><table><thead><tr>{''.join('<th>'+x+'</th>' for x in ('Module','Group','Test','Status','ms','Device','Sent','Received','Details','Blocker'))}</tr></thead><tbody>{body}</tbody></table></main>"""
    (output / "dashboard.html").write_text(page, encoding="utf-8")
    (ROOT / "latest_enterprise_dashboard.html").write_text(page, encoding="utf-8")
    (ROOT / "latest_dashboard.html").write_text(page, encoding="utf-8")
    (ROOT / "latest_report.txt").write_text(str(output.resolve()), encoding="utf-8")
    return document


def main():
    with NETWORK_CALLS_LOCK:
        NETWORK_CALLS.clear()
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
    selection = json.loads(args.selection.read_text(encoding="utf-8-sig"))
    started = datetime.now().astimezone()
    output = ROOT / "reports" / ("enterprise_" + started.strftime("%Y-%m-%d_%H%M%S"))
    output.mkdir(parents=True)
    inventory = discover(config)
    mode = selection.get("mode", "combined")
    events = []
    server_rows = [server_status_check(config, float(selection.get("timeout_seconds", 40)))] \
        if mode in ("messages", "fixed_batch", "dummy", "combined") else []
    if mode == "messages":
        rows, events = message_suite(selection, config)
    elif mode == "fixed_batch":
        rows, events = fixed_batch_suite(selection, config)
    elif mode == "dummy":
        rows, events = dummy_suite(selection, config)
    elif mode == "real":
        rows, events = real_device_suite(selection, config, inventory)
    elif mode == "desktop":
        rows = frontend_suite(selection, config, output, inventory)
    else:
        rows = frontend_suite(selection, config, output, inventory) + backend_suite(selection, config)
    rows = server_rows + rows
    report = write_report(output, selection, inventory, rows, started, events)
    print(json.dumps({"output": str(output.resolve()), "summary": report["summary"]}, indent=2))
    return 1 if report["summary"]["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
