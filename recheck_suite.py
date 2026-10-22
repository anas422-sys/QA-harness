"""One-file reCheck360 testing suite.

Run: python recheck_suite.py
CLI: python recheck_suite.py all
Offline check: python recheck_suite.py self-test
Dependencies: python -m pip install requests websocket-client psutil

The code for all five earlier scripts is included below; those files are not
required. Optional legacy configuration is read from locustfile.py if present.
Use RECHECK_LOGIN_URL, RECHECK_WS_URL, RECHECK_USERNAME, RECHECK_PASSWORD to
configure a standalone copy. No credentials are embedded in this script.
"""
import os
try:
    import requests
except ImportError:
    requests = None
try:
    import websocket
except ImportError:
    websocket = None

# ---------------------------------------------------------------------------
# run_session_load.py (self-contained session functions)
# ---------------------------------------------------------------------------
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
session_ROOT = Path(__file__).resolve().parent

def session_settings():
    return suite_settings()

def session_percentile(values, fraction):
    return round(sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)], 2) if values else None

def session_main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--users', type=int, default=20)
    parser.add_argument('--hold', type=int, default=60, help='Seconds after all users finish starting.')
    parser.add_argument('--spawn-rate', type=float, default=2)
    args = parser.parse_args()
    if not 1 <= args.users <= 20 or args.hold < 5 or args.spawn_rate <= 0:
        parser.error('users must be 1..20; hold >=5; spawn-rate >0')
    cfg = session_settings()
    out = suite_output('transport')
    out.mkdir(parents=True)
    lock = threading.Lock()
    stop = threading.Event()
    startup = [threading.Event() for _ in range(args.users)]
    events = []
    history = []
    rows = [dict(user_id=f'session-{i + 1:02d}', login_ok=False, connection_ok=False, successful_pongs=0, failures=0, difficulties=[]) for i in range(args.users)]
    active = 0
    peak = 0
    start = time.monotonic()

    def record(row, step, started, error=None):
        item = dict(user_id=row['user_id'], step=step, elapsed_s=round(time.monotonic() - start, 3), duration_ms=round((time.perf_counter() - started) * 1000, 2), error=error)
        with lock:
            events.append(item)
            if error:
                row['failures'] += 1
                row['difficulties'].append(step + ': ' + error)

    def worker(index):
        nonlocal active, peak
        row = rows[index]
        ws = None
        counted = False
        step = 'login'
        started = time.perf_counter()
        try:
            with requests.Session() as client:
                with client.post(cfg['LOGIN_URL'], json={'username': cfg['USERNAME'], 'password': cfg['PASSWORD']}, timeout=15, allow_redirects=False) as response:
                    if response.status_code != 200:
                        raise ValueError('HTTP ' + str(response.status_code))
                    data = response.json()
                    nested = data.get('data') or {}
                    token = data.get('token') or data.get('access_token') or nested.get('token') or nested.get('access_token')
                    if not isinstance(token, str) or not token:
                        raise ValueError('missing token')
                row['login_ok'] = True
                record(row, step, started)
                step = 'connect'
                started = time.perf_counter()
                ws = websocket.create_connection(cfg['WS_URL'], header={'Authorization': 'Bearer ' + token}, timeout=10)
                row['connection_ok'] = True
                with lock:
                    active += 1
                    counted = True
                    peak = max(peak, active)
                    history.append(dict(elapsed_s=round(time.monotonic() - start, 3), open_sessions=active))
                record(row, step, started)
                startup[index].set()
                while not stop.is_set():
                    step = 'ping_pong'
                    started = time.perf_counter()
                    marker = (row['user_id'] + '-' + str(row['successful_pongs'])).encode()
                    ws.ping(marker)
                    deadline = time.monotonic() + 10
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError()
                        ws.settimeout(remaining)
                        opcode, frame = ws.recv_data_frame(control_frame=True)
                        if opcode == websocket.ABNF.OPCODE_CLOSE:
                            raise ConnectionError()
                        if opcode == websocket.ABNF.OPCODE_PONG and frame.data == marker:
                            break
                    row['successful_pongs'] += 1
                    record(row, step, started)
                    stop.wait(5)
        except Exception as error:
            category = str(error) if type(error) is ValueError and (str(error).startswith('HTTP ') or str(error) == 'missing token') else type(error).__name__
            record(row, step, started, category)
        finally:
            startup[index].set()
            if counted:
                with lock:
                    active -= 1
                    history.append(dict(elapsed_s=round(time.monotonic() - start, 3), open_sessions=active))
            if ws:
                try:
                    ws.close(timeout=1)
                except Exception:
                    pass
    with ThreadPoolExecutor(max_workers=args.users) as pool:
        jobs = []
        for index in range(args.users):
            jobs.append(pool.submit(worker, index))
            if index + 1 < args.users:
                time.sleep(1 / args.spawn_rate)
        for ready in startup:
            ready.wait()
        with lock:
            held_at_start = active
        hold_started = time.monotonic()
        print(f'Started {args.users} sessions; {held_at_start} sockets open. Holding for {args.hold}s.', flush=True)
        try:
            stop.wait(args.hold)
        finally:
            with lock:
                held_at_end = active
            stop.set()
        for job in jobs:
            job.result()
    by_step = {}
    for step in ('login', 'connect', 'ping_pong'):
        samples = [e for e in events if e['step'] == step]
        times = [e['duration_ms'] for e in samples if e['error'] is None]
        by_step[step] = dict(attempts=len(samples), failures=sum((e['error'] is not None for e in samples)), successful_p50_ms=session_percentile(times, 0.5), successful_p95_ms=session_percentile(times, 0.95), successful_max_ms=max(times) if times else None)
    summary = dict(scope='shared-account login and WebSocket transport only', target_sessions=args.users, peak_open_sessions=peak, open_sessions_at_hold_start=held_at_start, open_sessions_at_hold_end=held_at_end, requested_hold_seconds=args.hold, elapsed_seconds=round(time.monotonic() - start, 2), failures=sum((r['failures'] for r in rows)), steps=by_step, users=rows, connection_history=history)
    passed = held_at_start == args.users and held_at_end == args.users and (summary['failures'] == 0) and all((r['successful_pongs'] > 0 for r in rows))
    summary['transport_check'] = 'PASS' if passed else 'FAIL'
    (out / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    with (out / 'users.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (out / 'events.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(events[0]))
        writer.writeheader()
        writer.writerows(events)
    lines = ['# Concurrent session performance report', '', f"Transport check: {summary['transport_check']}. Target: {args.users} sessions.", f'Peak sockets: {peak}; hold start/end: {held_at_start}/{held_at_end}. Hold: {args.hold}s.', f"Failed operations: {summary['failures']}.", '', '| Step | Attempts | Failures | Successful p50 ms | Successful p95 ms |', '|---|---:|---:|---:|---:|']
    for step, item in by_step.items():
        lines.append(f"| {step} | {item['attempts']} | {item['failures']} | {item['successful_p50_ms']} | {item['successful_p95_ms']} |")
    lines += ['', '## Difficulties', '']
    difficulties = [f"- {r['user_id']}: {', '.join(r['difficulties'])}" for r in rows if r['difficulties']]
    lines += difficulties or ['- No login, connection, or ping/pong failures observed.']
    lines += ['', '## Meaning and limits', '', 'Login/setup times indicate potential waiting before connection; ping/pong measures network and WebSocket transport responsiveness.', 'These are simulated sessions sharing one account. Open sockets and pong replies do not establish that all sessions retain application authorization.', 'No diagnostic payloads were sent. No USB, hardware diagnostics, desktop UI response, or subjective user experience was measured.', 'This is an initial 20-session load probe, not a breaking-point stress test or proof of diagnostic capacity.', 'PASS means connections survived this interval with successful heartbeat checks; no product latency SLA was supplied.', 'Next: validate a diagnostic request/result contract, supply distinct test accounts/consistent synthetic fixtures, then run sustained diagnostic traffic.']
    (out / 'experience_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k not in ('users', 'connection_history')}, indent=2))
    print(f"Report: {out / 'experience_report.md'}")
    return 0 if passed else 1

# ---------------------------------------------------------------------------
# run_dummy_devices.py (self-contained dummy functions)
# ---------------------------------------------------------------------------
"""Dummy-device request probe/load test. Uses staging credentials from locustfile.py."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import plistlib
import threading
import time
import uuid
dummy_ROOT = Path(__file__).resolve().parent

def dummy_fixture(platform, number, run_id):
    identity = uuid.uuid5(uuid.NAMESPACE_URL, f'recheck-load/{run_id}/{platform}/{number}').hex
    if platform == 'ios':
        udid = identity[:8].upper() + '-' + identity[8:24].upper()
        info = dict(UniqueDeviceID=udid, SerialNumber='QA' + identity[:10].upper(), DeviceName=f'QA simulated iOS {number}', DeviceClass='iPhone', ProductType='iPhone13,1', ProductVersion='18.0', ModelNumber='QA_TEST', HardwareModel='D52gAP', ActivationState='Activated')
        encoded = plistlib.dumps(info, fmt=plistlib.FMT_XML)
    else:
        udid = 'QAANDROID' + identity[:12].upper()
        info = dict(serial=udid, manufacturer='QA', model='Simulated Android', android_version='14', device_name=f'QA simulated Android {number}')
        encoded = json.dumps(info).encode()
    return dict(client_data={'ref': int(identity[:12], 16)}, messagetype=1, udid=udid, device_operating_system=platform, operating_system='windows', device_info=base64.b64encode(encoded).decode())

def dummy_sanitized(value, key='', depth=0):
    if depth > 4:
        return '<nested>'
    if isinstance(value, dict):
        return {k: dummy_sanitized(v, k, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, list):
        return {'list_count': len(value), 'first_shape': dummy_sanitized(value[0], depth=depth + 1) if value else None}
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if key.lower() in ('status', 'error', 'message', 'detail', 'code', 'messagetype') and isinstance(value, str):
        text = value[:240]
        if any((word in text.lower() for word in ('token', 'password', 'bearer'))):
            return '<redacted>'
        return text
    return '<string>'

def dummy_classify(reply, payload):
    if not isinstance(reply, dict):
        return 'unvalidated_response'
    status = reply.get('status')
    if isinstance(status, str) and status.lower() in ('error', 'failed', 'failure', 'rejected') or reply.get('success') is False or reply.get('error'):
        return 'rejected'
    if reply.get('udid') != payload['udid'] or reply.get('client_data', {}).get('ref') != payload['client_data']['ref'] or reply.get('messagetype') != payload['messagetype']:
        return 'mismatched_response'
    if status == 'success':
        return 'acknowledged'
    return 'unvalidated_response'

def dummy_main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--per-platform', type=int, default=1)
    parser.add_argument('--rounds', type=int, default=12)
    parser.add_argument('--spawn-rate', type=float, default=2)
    args = parser.parse_args()
    if not 1 <= args.per_platform <= 10 or not 1 <= args.rounds <= 12 or args.spawn_rate <= 0:
        parser.error('per-platform must be 1..10 and rounds 1..12')
    cfg = session_settings()
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = suite_output('dummy')
    out.mkdir(parents=True)
    devices = [dict(platform=p, device_id=f'{p}-{n:02d}', payload=dummy_fixture(p, n, run_id)) for n in range(1, args.per_platform + 1) for p in ('ios', 'android')]
    ready = {d['device_id']: threading.Event() for d in devices}
    go = threading.Event()
    lock = threading.Lock()
    active = peak = 0
    events = []

    def worker(device):
        nonlocal active, peak
        ws = None
        connected = False
        result = dict(platform=device['platform'], device_id=device['device_id'], dummy_udid=device['payload']['udid'], login_ok=False, connection_ok=False, requests_sent=0, replies_received=0, acknowledged_requests=0, background_messages=0, diagnostics_completed=0, outcomes=[], response_samples=[])
        step = 'login'
        started = time.perf_counter()

        def event(outcome):
            with lock:
                events.append(dict(platform=device['platform'], device_id=device['device_id'], step=step, outcome=outcome, duration_ms=round((time.perf_counter() - started) * 1000, 2)))
        try:
            with requests.Session() as client:
                with client.post(cfg['LOGIN_URL'], json={'username': cfg['USERNAME'], 'password': cfg['PASSWORD']}, timeout=15, allow_redirects=False) as response:
                    if response.status_code != 200:
                        raise dummy_KnownError('HTTP ' + str(response.status_code))
                    body = response.json()
                    nested = body.get('data') or {}
                    token = body.get('token') or body.get('access_token') or nested.get('token') or nested.get('access_token')
                    if not isinstance(token, str) or not token:
                        raise dummy_KnownError('missing token')
                result['login_ok'] = True
                event('ok')
                step = 'connect'
                started = time.perf_counter()
                ws = websocket.create_connection(cfg['WS_URL'], header={'Authorization': 'Bearer ' + token}, timeout=15)
                result['connection_ok'] = True
                connected = True
                with lock:
                    active += 1
                    peak = max(peak, active)
                event('ok')
                step = 'synchronize'
                started = time.perf_counter()
                ready[device['device_id']].set()
                if not go.wait(timeout=90):
                    raise dummy_KnownError('start coordination timeout')
                for round_number in range(args.rounds):
                    step = 'device_request'
                    started = time.perf_counter()
                    device['payload']['client_data']['ref'] += 1
                    ws.send(json.dumps(device['payload']))
                    result['requests_sent'] += 1
                    deadline = time.monotonic() + 15
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise dummy_KnownError('matching response timeout')
                        ws.settimeout(remaining)
                        raw = ws.recv()
                        if not raw:
                            raise dummy_KnownError('connection closed')
                        try:
                            reply = json.loads(raw)
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            result['background_messages'] += 1
                            continue
                        if not isinstance(reply, dict) or reply.get('udid') != device['payload']['udid'] or reply.get('client_data', {}).get('ref') != device['payload']['client_data']['ref'] or (reply.get('messagetype') != 1):
                            result['background_messages'] += 1
                            continue
                        outcome = dummy_classify(reply, device['payload'])
                        break
                    result['replies_received'] += 1
                    if outcome == 'acknowledged':
                        result['acknowledged_requests'] += 1
                    result['outcomes'].append(outcome)
                    if len(result['response_samples']) < 2:
                        result['response_samples'].append(dummy_sanitized(reply))
                    event(outcome)
                    if outcome != 'acknowledged':
                        break
                    if round_number + 1 < args.rounds:
                        time.sleep(5)
        except Exception as exc:
            error = str(exc) if isinstance(exc, dummy_KnownError) else type(exc).__name__
            if isinstance(exc, websocket.WebSocketBadStatusException):
                error = 'websocket HTTP ' + str(exc.status_code)
            result['outcomes'].append(error)
            event(error)
        finally:
            ready[device['device_id']].set()
            if connected:
                with lock:
                    active -= 1
            if ws:
                try:
                    ws.close(timeout=1)
                except Exception:
                    pass
        return result
    with ThreadPoolExecutor(max_workers=len(devices)) as pool:
        jobs = []
        for index, device in enumerate(devices):
            jobs.append(pool.submit(worker, device))
            if index + 1 < len(devices):
                time.sleep(1 / args.spawn_rate)
        for signal in ready.values():
            signal.wait()
        print(f'Startup complete: {active}/{len(devices)} connected; starting dummy requests.', flush=True)
        go.set()
        results = [job.result() for job in jobs]
    groups = {}
    for platform in ('ios', 'android'):
        subset = [r for r in results if r['platform'] == platform]
        times = [e['duration_ms'] for e in events if e['platform'] == platform and e['step'] == 'device_request']
        groups[platform] = dict(dummy_devices=len(subset), login_ok=sum((r['login_ok'] for r in subset)), connections=sum((r['connection_ok'] for r in subset)), requests_sent=sum((r['requests_sent'] for r in subset)), replies_received=sum((r['replies_received'] for r in subset)), acknowledged_requests=sum((r['acknowledged_requests'] for r in subset)), devices_with_acknowledgment=sum((r['acknowledged_requests'] > 0 for r in subset)), explicitly_rejected=sum(('rejected' in r['outcomes'] for r in subset)), unvalidated_replies=sum(('unvalidated_response' in r['outcomes'] for r in subset)), background_messages=sum((r['background_messages'] for r in subset)), failed_devices=sum((any((o != 'acknowledged' for o in r['outcomes'])) for r in subset)), diagnostics_completed=0, request_attempt_p95_ms=session_percentile(times, 0.95))
    summary = dict(scope='exploratory synthetic device payloads, shared account', peak_connections=peak, spawn_rate=args.spawn_rate, requested_rounds=args.rounds, platforms=groups, devices=results, limitations=['Android device_info schema is assumed, not verified.', 'Synthetic iOS fixture contains only a subset of real-device plist fields.', 'Acknowledgment requires status=success and matching udid, client_data.ref and messagetype; it does not prove diagnostic completion.', 'No hardware/USB or desktop UI behavior is exercised.', 'Only message type 1 is repeated; returned hardware commands are not executed. Unmatched/non-JSON messages are counted separately; each request waits up to 15 seconds for its matching reply.'])
    (out / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    import csv
    with (out / 'devices.csv').open('w', newline='', encoding='utf-8') as handle:
        fields = ['platform', 'device_id', 'dummy_udid', 'login_ok', 'connection_ok', 'requests_sent', 'replies_received', 'acknowledged_requests', 'background_messages', 'diagnostics_completed', 'outcomes']
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(results)
    (out / 'events.json').write_text(json.dumps(events, indent=2), encoding='utf-8')
    lines = ['# Dummy iOS and Android device test', '', 'This measures synthetic device-request acknowledgments, not completed hardware diagnostics.', f'Peak concurrent sockets: {peak}.', '', '| Platform | Dummy devices | Requests sent | Acknowledged requests | Explicit rejections | Verified diagnostics |', '|---|---:|---:|---:|---:|---:|']
    for platform, g in groups.items():
        lines.append(f"| {platform} | {g['dummy_devices']} | {g['requests_sent']} | {g['acknowledged_requests']} | {g['explicitly_rejected']} | 0 |")
    lines += ['', '## Per-device observations', '']
    lines += [f"- {r['device_id']}: {', '.join(r['outcomes']) or 'no outcome'}." for r in results]
    lines += ['', '## Limits', ''] + ['- ' + s for s in summary['limitations']]
    (out / 'experience_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'devices'}, indent=2))
    print(f"Report: {out / 'experience_report.md'}")
    return 1 if any((g['failed_devices'] for g in groups.values())) else 0

class dummy_KnownError(Exception):
    pass

# ---------------------------------------------------------------------------
# device_experience_report.py (self-contained observation functions)
# ---------------------------------------------------------------------------
"""Generate a report from observations on 20 real devices; no third-party packages."""
import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
observation_FIELDS = ['user_id', 'device_id', 'device_model', 'os_version', 'app_version', 'network', 'started_at', 'finished_at', 'login_status', 'login_seconds', 'connection_status', 'connection_seconds', 'diagnostic_status', 'diagnostic_seconds', 'crashed', 'froze', 'difficulty', 'recovery', 'evidence']
observation_STEPS = ('login', 'connection', 'diagnostic')

def observation_p95(values):
    return sorted(values)[math.ceil(len(values) * 0.95) - 1] if values else None

def observation_timestamp(value):
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError('Timestamps must include timezone, e.g. 2026-09-10T14:00:00+05:00')
    return result

def observation_generate(source, output, target):
    with source.open(newline='', encoding='utf-8-sig') as handle:
        reader = csv.DictReader(handle)
        if not set(observation_FIELDS).issubset(reader.fieldnames or []):
            raise ValueError('CSV is missing required columns; use --init.')
        rows = list(reader)
    if len(rows) != target:
        raise ValueError(f'Expected {target} device rows, found {len(rows)}.')
    users = [r['user_id'].strip() for r in rows]
    if len(set(users)) != target or not all(users):
        raise ValueError('Every row must have a unique user_id.')
    ids = [r['device_id'].strip() for r in rows if r['device_id'].strip()]
    if len(ids) != len(set(ids)):
        raise ValueError('device_id values must be unique.')
    intervals = []
    for index, row in enumerate(rows, 2):
        for step in observation_STEPS:
            status = row[step + '_status'].strip().lower()
            row[step + '_status'] = status
            if status not in ('', 'pass', 'fail', 'blocked', 'not_run'):
                raise ValueError(f'Row {index}: invalid {step} status.')
            value = row[step + '_seconds']
            if value:
                seconds = float(value)
                if not math.isfinite(seconds) or seconds < 0:
                    raise ValueError(f'Row {index}: duration must be finite and nonnegative.')
                row[step + '_seconds'] = seconds
            if status in ('pass', 'fail', 'blocked') and (not row['device_id'].strip()):
                raise ValueError(f'Row {index}: observed result requires device_id.')
        for key in ('crashed', 'froze'):
            row[key] = row[key].strip().lower()
            if row[key] not in ('', 'yes', 'no'):
                raise ValueError(f'Row {index}: {key} must be yes, no, or blank.')
        if bool(row['started_at']) != bool(row['finished_at']):
            raise ValueError(f'Row {index}: provide both start and finish timestamps.')
        if row['started_at']:
            start, end = (observation_timestamp(row['started_at']), observation_timestamp(row['finished_at']))
            if end <= start:
                raise ValueError(f'Row {index}: finish must be after start.')
            intervals.append((start, end))
    complete = sum((all((r[s + '_status'] == 'pass' for s in observation_STEPS)) for r in rows))
    observed = sum((any((r[s + '_status'] in ('pass', 'fail', 'blocked') for s in observation_STEPS)) for r in rows))
    points = [(a, 1) for a, b in intervals] + [(b, -1) for a, b in intervals]
    active = peak = 0
    for _, change in sorted(points):
        active += change
        peak = max(peak, active)
    overlap = max(0, (min((b for a, b in intervals)) - max((a for a, b in intervals))).total_seconds()) if len(intervals) == target else None
    stats = {}
    for step in observation_STEPS:
        durations = [r[step + '_seconds'] for r in rows if r[step + '_seconds'] != '']
        stats[step] = dict(statuses=dict(Counter((r[step + '_status'] or 'unrecorded' for r in rows))), timed_samples=len(durations), p95_seconds=observation_p95(durations))
    summary = dict(target_devices=target, observed_devices=observed, successful_journeys=complete, peak_overlapping_journeys=peak, all_device_journey_overlap_seconds=overlap, crashes=sum((r['crashed'] == 'yes' for r in rows)), freezes=sum((r['froze'] == 'yes' for r in rows)), steps=stats, devices=rows)
    lines = ['# Real-device experience report', '', f'Observed devices: {observed}/{target}. Successful full journeys: {complete}/{target}.', f"Reported crashes: {summary['crashes']}. Reported freezes: {summary['freezes']}.", f'Peak overlapping recorded journeys: {peak}.', f"Overlap across all {target} device journeys (seconds): {(overlap if overlap is not None else 'not established')}.", '', 'Times are tester observations. Overlapping journeys do not prove simultaneous backend requests or diagnostics.', 'Blank fields mean unrecorded, never success. p95 includes all supplied durations, including failures.', '', '## Actions', '']
    for step, data in stats.items():
        lines.append(f"- {step}: {data['statuses']}; timed samples {data['timed_samples']}; p95 {data['p95_seconds']} seconds.")
    lines += ['', '## User difficulties and recovery', '']
    for r in rows:
        statuses = ', '.join((f"{s}={r[s + '_status'] or 'unrecorded'}" for s in observation_STEPS))
        lines.append(f"- {r['user_id']}: {statuses}. Difficulty: {r['difficulty'] or 'unrecorded'}. Recovery: {r['recovery'] or 'unrecorded'}. Evidence: {r['evidence'] or 'unrecorded'}.")
    lines += ['', '## Interpretation', '', 'Confirm defects using screenshots, screen recordings, application logs and matching server timestamps.', 'No root cause, subjective feedback, or device behavior is inferred from missing evidence.']
    output.mkdir(parents=True, exist_ok=True)
    (output / 'experience_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary

def observation_main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--init', action='store_true', help='Create a blank real-device observation CSV.')
    parser.add_argument('--csv', type=Path, default=Path('device_observations.csv'))
    parser.add_argument('--devices', type=int, default=20)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.devices < 1:
        parser.error('--devices must be positive')
    if args.init:
        with args.csv.open('x', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=observation_FIELDS)
            writer.writeheader()
            writer.writerows(({'user_id': f'user-{i:02d}'} for i in range(1, args.devices + 1)))
        print(f'Created {args.csv} with {args.devices} blank observations.')
    else:
        output = args.output or Path('reports') / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        summary = observation_generate(args.csv, output, args.devices)
        print(f"Report: {output / 'experience_report.md'}")
        print(f"Observed {summary['observed_devices']}/{args.devices} devices.")

# ---------------------------------------------------------------------------
# capture_diagnostic_flow.py (self-contained capture functions)
# ---------------------------------------------------------------------------
"""Extract redacted request/reply timelines from reCheck360 logs; never replay hardware commands."""
import argparse
from collections import Counter, defaultdict, deque
from datetime import datetime
import csv
import json
from pathlib import Path
import time
capture_LABELS = {1: 'Device information', 3: 'Battery command request (inferred)', 4: 'Battery results', 5: 'OEM command request (inferred)', 6: 'OEM results', 7: 'Validation command request (inferred)', 8: 'Validation results', 12: 'App-install command request', 138: '3uTools integration data', 140: 'OEM2 data'}
capture_DEVICE_TYPES = set(capture_LABELS)

def capture_shape(value, key=''):
    """Keep field names and types, never account/device/command/result values."""
    if isinstance(value, dict):
        return {k: capture_shape(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return {'type': 'array', 'items': capture_shape(value[0]) if value else None, 'count': len(value)}
    if key in ('messagetype', 'cmd_id') and isinstance(value, int):
        return value
    if isinstance(value, str):
        return {'type': 'string', 'length': len(value)}
    return {'type': type(value).__name__}

def capture_parse(lines):
    records = []
    aliases = {}
    references = {}
    skipped = 0
    for number, line in enumerate(lines, 1):
        if 'WebSocketManager' not in line:
            continue
        direction = 'sent' if 'Message sent:' in line else 'received' if 'Received message:' in line else None
        if not direction or '{' not in line:
            continue
        try:
            timestamp = datetime.strptime(line[:23], '%Y-%m-%d %H:%M:%S.%f')
            obj = json.JSONDecoder().raw_decode(line[line.index('{'):])[0]
            if not isinstance(obj, dict):
                raise ValueError()
        except (ValueError, TypeError):
            skipped += 1
            continue
        kind = obj.get('messagetype')
        if not isinstance(kind, int):
            skipped += 1
            continue
        client = obj.get('client_data')
        ref = client.get('ref') if isinstance(client, dict) else None
        if ref is not None:
            raw_ref = json.dumps(ref, sort_keys=True)
            reference = references.setdefault(raw_ref, f'request-{len(references) + 1:03d}')
        else:
            reference = None
        identity = obj.get('udid')
        reply = obj.get('reply')
        if not identity and isinstance(reply, dict):
            identity = reply.get('udid')
        alias = aliases.setdefault(str(identity), f'device-{len(aliases) + 1:02d}') if identity else None
        status = obj.get('status')
        safe_status = status if isinstance(status, str) and status.lower() in ('success', 'error', 'failed', 'failure', 'pending', 'ok') else 'other' if status is not None else None
        records.append(dict(line=number, time=timestamp.isoformat(timespec='milliseconds'), direction=direction, message_type=kind, device=alias, request=reference, status=safe_status, schema=capture_shape(obj)))
    return (records, skipped)

def capture_analyze(records):
    pending = defaultdict(deque)
    exchanges = []
    notifications = 0
    for event in records:
        key = (event['message_type'], event['request'])
        if event['direction'] == 'sent':
            if event['request'] is not None:
                pending[key].append(event)
            else:
                exchanges.append(dict(message_type=event['message_type'], device=event['device'], request=None, sent_at=event['time'], reply_at=None, duration_ms=None, outcome='uncorrelatable_send'))
        elif event['request'] is not None and pending[key]:
            request = pending[key][0]
            if request['device'] and event['device'] and (request['device'] != event['device']):
                notifications += 1
                continue
            pending[key].popleft()
            elapsed = (datetime.fromisoformat(event['time']) - datetime.fromisoformat(request['time'])).total_seconds() * 1000
            outcome = 'acknowledged' if event['status'] in ('success', 'ok') else 'reply_' + str(event['status'])
            exchanges.append(dict(message_type=event['message_type'], device=request['device'] or event['device'], request=event['request'], sent_at=request['time'], reply_at=event['time'], duration_ms=round(elapsed, 2), outcome=outcome))
        else:
            notifications += 1
    for queue in pending.values():
        for event in queue:
            exchanges.append(dict(message_type=event['message_type'], device=event['device'], request=event['request'], sent_at=event['time'], reply_at=None, duration_ms=None, outcome='no_reply_in_capture'))
    exchanges.sort(key=lambda e: e['sent_at'])
    return (exchanges, notifications)

def capture_write_report(records, skipped, output, source, metrics=None, scope='existing log'):
    output.mkdir(parents=True, exist_ok=False)
    exchanges, notifications = capture_analyze(records)
    groups = []
    for kind in sorted({r['message_type'] for r in records}):
        items = [e for e in exchanges if e['message_type'] == kind]
        times = [e['duration_ms'] for e in items if e['duration_ms'] is not None]
        groups.append(dict(message_type=kind, label=capture_LABELS.get(kind, 'Unmapped application message'), outgoing=len(items), matched=sum((e['reply_at'] is not None for e in items)), outcomes=dict(Counter((e['outcome'] for e in items))), max_reply_ms=max(times) if times else None))
    summary = dict(source_filename=source.name, scope=scope, recorded_messages=len(records), skipped_unparseable_messages=skipped, pseudonymous_devices=len({r['device'] for r in records if r['device']}), unpaired_received_messages=notifications, steps=groups, complete_diagnostic_journey_verified=False)
    (output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    (output / 'protocol_schemas.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    with (output / 'timeline.csv').open('w', newline='', encoding='utf-8') as handle:
        fields = ['message_type', 'device', 'request', 'sent_at', 'reply_at', 'duration_ms', 'outcome']
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(exchanges)
    if metrics is not None:
        (output / 'desktop_metrics.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
    lines = ['# Diagnostic protocol capture', '', f'Scope: {scope}. Source: {source.name}.', f"Messages: {len(records)}. Device identities observed: {summary['pseudonymous_devices']}.", f'Unpaired received messages: {notifications}; unparseable messages skipped: {skipped}.', '', '## Recorded request/reply steps', '', '| Type | Observed step | Requests | Matched replies | Max logged reply time ms |', '|---|---|---:|---:|---:|']
    for g in groups:
        lines.append(f"| {g['message_type']} | {g['label']} | {g['outgoing']} | {g['matched']} | {g['max_reply_ms']} |")
    lines += ['', '## What this establishes', '', 'The timeline matches logged outgoing requests to incoming replies by message type and request reference, checking device identity when both sides include it.', 'Device identifiers and references are replaced by local labels. Schemas retain field names, types and string lengths, not credentials or hardware data.', 'Timestamps are local application log times. Differences measure logged request/reply intervals, not total hardware execution or UI response.', 'No reply in this capture does not prove a timeout; the reply may fall outside the captured log or logging coverage.', 'An acknowledged payload is not proof that a full diagnostic passed. Final diagnostic completion has not been verified.', '', '## Next protocol work', '', "Build synthetic command-result fixtures for each observed step; do not replay this phone's data.", "Validate Android's separate command/result schemas using a real Android capture.", 'Identify the explicit final diagnostic completion/result-save event and verify that the dashboard agrees.', 'Compiled message-name constants are not treated as authoritative: the log uses message numbers differently in some cases.', 'Only then extend the simulator to a complete journey. Do not execute commands from captured or server-returned payloads automatically.']
    (output / 'capture_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return summary

def capture_main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--log', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--watch-seconds', type=int, default=0, help='Capture newly appended log lines and desktop resource samples.')
    args = parser.parse_args()
    if args.watch_seconds < 0:
        parser.error('watch-seconds must be nonnegative')
    files = list((Path.home() / '.recheck360' / 'logs').glob('app-*.log'))
    source = args.log or (max(files, key=lambda p: p.stat().st_mtime) if files else None)
    if source is None:
        parser.error('No application log found; provide --log.')
    metrics = None
    scope = 'existing log, historical observations'
    if args.watch_seconds:
        import psutil
        scope = f'new log lines during {args.watch_seconds}-second capture; no automatic UI actions'
        offset = source.stat().st_size
        metrics = []
        tracked = {}
        deadline = time.monotonic() + args.watch_seconds
        print('Capturing new log activity and reCheck360 resource use.', flush=True)
        while time.monotonic() < deadline:
            sample = dict(time=datetime.now().isoformat(timespec='seconds'), processes=[])
            for proc in psutil.process_iter(['pid', 'name']):
                if (proc.info['name'] or '').lower() != 'recheck360.exe':
                    continue
                try:
                    key = (proc.pid, proc.create_time())
                    old = tracked.get(key)
                    if old is None:
                        tracked[key] = proc
                        proc.cpu_percent()
                        cpu = None
                    else:
                        proc = old
                        cpu = proc.cpu_percent()
                    sample['processes'].append(dict(pid=proc.pid, cpu_percent_one_core=cpu, rss_mb=round(proc.memory_info().rss / 1024 ** 2, 2), threads=proc.num_threads()))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            metrics.append(sample)
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        if source.stat().st_size < offset:
            raise RuntimeError('Log rotated or truncated; capture again against the current log.')
        with source.open('rb') as handle:
            handle.seek(offset)
            lines = handle.read().decode('utf-8', errors='replace').splitlines()
    else:
        lines = source.read_text(encoding='utf-8', errors='replace').splitlines()
    records, skipped = capture_parse(lines)
    output = args.output or Path(__file__).resolve().parent / 'reports' / datetime.now().strftime('protocol-%Y%m%dT%H%M%S%f')
    summary = capture_write_report(records, skipped, output, source, metrics, scope)
    print(json.dumps(summary, indent=2))
    print(f"Report: {output / 'capture_report.md'}")

# ---------------------------------------------------------------------------
# analyze_diagnostic_results.py (self-contained results functions)
# ---------------------------------------------------------------------------
"""Report real diagnostic result snapshots and compare them with the logged test plan."""
import argparse
from collections import Counter
import csv
from datetime import datetime
import json
from pathlib import Path
results_PASS = {'pass', 'passed'}
results_FAIL = {'fail', 'failed'}
results_NOT_APPLICABLE = {'not applicable', 'n/a', 'not_applicable'}
results_SKIPPED = {'skipped', 'skip'}

def results_evaluate(tests, plan=None, excluded=()):
    codes = [t.get('code') for t in tests]
    duplicates = [code for code, count in Counter(codes).items() if count > 1]
    actual = {t.get('code'): t for t in tests if isinstance(t.get('code'), str) and t['code']}
    required = {t['code']: t for t in plan or [] if t.get('is_enabled') is True and isinstance(t.get('code'), str)}
    exclusions = set(excluded)
    expected = set(required) - exclusions
    missing = sorted(expected - set(actual))
    rows = []
    for test in tests:
        raw = str(test.get('result', '')).strip()
        status = raw.lower()
        category = 'pass' if status in results_PASS else 'fail' if status in results_FAIL else 'not_applicable' if status in results_NOT_APPLICABLE else 'skipped' if status in results_SKIPPED else 'unresolved'
        rows.append(dict(code=test.get('code'), test_name=test.get('test_name'), result=raw, category=category, enabled=test.get('is_enabled'), hidden=test.get('is_hidden')))
    counts = dict(Counter((row['category'] for row in rows)))
    unresolved = [row['code'] for row in rows if row['category'] in ('unresolved', 'skipped') and row['code'] in expected]
    known_plan = plan is not None and bool(expected)
    invalid_codes = any((not isinstance(c, str) or not c for c in codes))
    coverage = known_plan and (not missing) and (not duplicates) and (not invalid_codes) and (not unresolved)
    return dict(result_count=len(rows), expected_enabled_count=len(required) if plan is not None else None, required_after_exclusions=len(expected) if plan is not None else None, counts=counts, missing_tests=[dict(code=c, test_name=required[c].get('test_name')) for c in missing], excluded_codes=sorted(exclusions), duplicate_codes=duplicates, unresolved_required_codes=unresolved, reported_required_results_complete=bool(coverage), all_required_reported_pass=bool(coverage and all((str(actual[c].get('result', '')).lower().strip() in results_PASS for c in expected))), fresh_diagnostic_run_verified=False, tests=rows)

def results_extract(lines, excluded=()):
    plans = {}
    devices = {}
    platforms = {}
    snapshots = []
    for line in lines:
        if 'WebSocketManager' not in line or '{' not in line:
            continue
        try:
            obj = json.JSONDecoder().raw_decode(line[line.index('{'):])[0]
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        identity = obj.get('udid')
        if identity:
            device = devices.setdefault(str(identity), f'device-{len(devices) + 1:02d}')
            platform = obj.get('device_operating_system')
            if platform in ('ios', 'android'):
                platforms[device] = platform
        else:
            device = None
        if 'Received message:' not in line:
            continue
        reply = obj.get('reply')
        if not isinstance(reply, dict):
            continue
        kind = obj.get('messagetype')
        if kind == 32 and isinstance(reply.get('tests'), list):
            plans[reply.get('name')] = reply['tests']
        if kind != 15 or not isinstance(reply.get('tests'), list):
            continue
        snapshot = dict(timestamp=line[:23], device=device or 'unassociated', platform=platforms.get(device, 'unknown'), message_type=15, success_envelope=obj.get('status') == 'success', **results_evaluate(reply['tests'], plans.get(reply.get('name')), excluded))
        if not snapshot['success_envelope'] or device is None:
            snapshot['reported_required_results_complete'] = False
            snapshot['all_required_reported_pass'] = False
        snapshots.append(snapshot)
    return snapshots

def results_main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--log', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--exclude-code', action='append', default=[], help='Explicitly exclude a code only after confirming device applicability.')
    args = parser.parse_args()
    files = list((Path.home() / '.recheck360/logs').glob('app-*.log'))
    source = args.log or (max(files, key=lambda p: p.stat().st_mtime) if files else None)
    if source is None:
        parser.error('No log found; provide --log')
    snapshots = results_extract(source.read_text(encoding='utf-8', errors='replace').splitlines(), args.exclude_code)
    latest = {}
    for snapshot in snapshots:
        latest[snapshot['device']] = snapshot
    out = args.output or Path(__file__).resolve().parent / 'reports' / datetime.now().strftime('diagnostic-results-%Y%m%dT%H%M%S%f')
    out.mkdir(parents=True, exist_ok=False)
    summary = dict(source=source.name, snapshot_events=len(snapshots), devices_with_result_snapshots=len(latest), devices=list(latest.values()), all_snapshots=snapshots, scope='stored/reported diagnostic results, not proof of a fresh test run')
    (out / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    with (out / 'test_results.csv').open('w', newline='', encoding='utf-8') as handle:
        fields = ['device', 'platform', 'snapshot_time', 'code', 'test_name', 'result', 'category', 'enabled', 'hidden']
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for device in latest.values():
            for test in device['tests']:
                writer.writerow(dict(device=device['device'], platform=device['platform'], snapshot_time=device['timestamp'], **test))
    lines = ['# Individual diagnostic results', '', f'Result snapshot events: {len(snapshots)}. Devices with snapshots: {len(latest)}.', 'These are server-reported results from message type 15. Fresh-run completion and hardware accuracy are not independently established.', '', '| Device | Platform | Reported tests | Pass | Fail | Enabled in matching plan | Missing required |', '|---|---|---:|---:|---:|---:|---:|']
    for device in latest.values():
        counts = device['counts']
        lines.append(f"| {device['device']} | {device['platform']} | {device['result_count']} | {counts.get('pass', 0)} | {counts.get('fail', 0)} | {device['expected_enabled_count']} | {len(device['missing_tests'])} |")
    lines += ['', '## Coverage findings', '']
    for device in latest.values():
        lines.append(f"- {device['device']}: all required results accounted for = {device['reported_required_results_complete']}.")
        for missing in device['missing_tests']:
            lines.append(f"- No result for {missing['test_name']} ({missing['code']}). Confirm hardware applicability before calling this a failed or omitted test.")
    if not latest:
        lines.append('- No result snapshot found. No completed diagnostic is claimed.')
    lines += ['', '## Individual reported outcomes', '', '| Device | Code | Test | Result |', '|---|---|---|---|']
    for device in latest.values():
        for test in device['tests']:
            values = [device['device'], test['code'], test['test_name'], test['result']]
            lines.append('| ' + ' | '.join((str(v).replace('|', '/').replace('\n', ' ') for v in values)) + ' |')
    lines += ['', '## Completion contract for future load tests', '', "A status=success acknowledgment is insufficient. Observe the correct device's type-15 result snapshot and compare the required test codes with an applicable test plan.", 'Match the snapshot to the current diagnostic cycle using an authoritative cycle ID or documented fresh-result rule. Type 15 in this capture has no request reference.', 'A new receive timestamp is not proof the tests ran recently; saved results may be pushed when a device reconnects.', 'Treat pass/fail as terminal reported outcomes, keep skipped/pending/missing results separate, and require explicit applicability for excluded tests.', 'Record elapsed time from a verified diagnostic start to its matching final result event; this capture does not establish that start/end pair.', "Android requires its own observed result contract and applicable test plan. Do not fabricate passing results or replay this phone's identity.", 'The current dummy-device runner remains a message-type-1 load test.']
    (out / 'results_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k not in ('devices', 'all_snapshots')}, indent=2))
    for device in latest.values():
        print(json.dumps({k: v for k, v in device.items() if k != 'tests'}, indent=2))
    print(f"Report: {out / 'results_report.md'}")

# ---------------------------------------------------------------------------
# Unified runner: configuration, monitoring, reports and menu
# ---------------------------------------------------------------------------

import contextlib
import getpass
import html
import io
import sys
import tempfile
import types

SUITE_HOME = Path(__file__).resolve().parent
SUITE_OUTPUT = None
SUITE_CONFIG = None


def suite_output(name):
    if SUITE_OUTPUT is None:
        raise RuntimeError("Start a suite run before invoking a component.")
    return SUITE_OUTPUT / name


def suite_settings():
    if SUITE_CONFIG is None:
        raise ValueError("Connection settings are not configured.")
    return dict(SUITE_CONFIG)


def configure_network(args):
    global SUITE_CONFIG
    values = {}
    # Optional migration support only: the other scripts are not imported.
    legacy = SUITE_HOME / "locustfile.py"
    if legacy.exists():
        try:
            tree = ast.parse(legacy.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                    key = node.targets[0].id
                    if key in ("LOGIN_URL", "WS_URL", "USERNAME", "PASSWORD"):
                        value = ast.literal_eval(node.value)
                        if isinstance(value, str):
                            values[key] = value
        except (ValueError, SyntaxError, OSError):
            pass
    for key in ("LOGIN_URL", "WS_URL", "USERNAME", "PASSWORD"):
        value = os.environ.get("RECHECK_" + key)
        if value:
            values[key] = value
    for key, value in (("LOGIN_URL", args.login_url), ("WS_URL", args.ws_url), ("USERNAME", args.username)):
        if value:
            values[key] = value
    values.setdefault("LOGIN_URL", "https://staging.phone-diagnostics.com/v1/login")
    values.setdefault("WS_URL", "wss://staging.phone-diagnostics.com/v1/ws")
    if sys.stdin.isatty():
        if not values.get("USERNAME"):
            values["USERNAME"] = input("Staging test username: ").strip()
        if not values.get("PASSWORD"):
            values["PASSWORD"] = getpass.getpass("Staging test password: ")
    if not values.get("USERNAME") or not values.get("PASSWORD"):
        raise ValueError("Set RECHECK_USERNAME and RECHECK_PASSWORD, or run interactively.")
    from urllib.parse import urlparse
    for key, schemes in (("LOGIN_URL", ("http", "https")), ("WS_URL", ("ws", "wss"))):
        url = urlparse(values[key])
        if url.scheme not in schemes or not url.hostname or url.username or url.password:
            raise ValueError("Provide valid HTTP and WebSocket URLs without embedded credentials.")
    if requests is None or websocket is None:
        raise ValueError("Install dependencies: python -m pip install requests websocket-client psutil")
    SUITE_CONFIG = values


def latest_log(explicit=None):
    if explicit:
        if not explicit.is_file():
            raise ValueError("The specified application log was not found.")
        return explicit
    candidates = list((Path.home() / ".recheck360" / "logs").glob("app-*.log"))
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def run_component(name, function, arguments):
    old_argv = sys.argv
    stream = io.StringIO()
    print("Running " + name + "...", flush=True)
    code = 0
    error = None
    try:
        sys.argv = [name] + list(arguments)
        with contextlib.redirect_stdout(stream):
            code = function() or 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        error = "component exited" if code else None
    except Exception as exc:
        code = 1
        # Do not persist arbitrary exception messages containing tokens or response bodies.
        error = type(exc).__name__
    finally:
        sys.argv = old_argv
    (SUITE_OUTPUT / (name + "_console.txt")).write_text(stream.getvalue(), encoding="utf-8")
    outcome = dict(component=name, exit_code=code,
                   status="completed" if code == 0 else "failed", error=error)
    print(name + ": " + outcome["status"], flush=True)
    return outcome


class DesktopMonitor:
    """Sample the desktop during load, independently of component stdout/argv."""
    def __init__(self, log):
        self.log = log
        self.offset = log.stat().st_size if log else None
        self.log_identity = (log.stat().st_dev, log.stat().st_ino) if log else None
        self.stop = threading.Event()
        self.samples = []
        self.error = None
        self.thread = None
        self.started = datetime.now().isoformat(timespec="seconds")

    def start(self):
        try:
            import psutil
        except ImportError:
            self.error = "psutil unavailable; install it for desktop metrics"
            return
        def collect():
            tracked = {}
            try:
                while not self.stop.is_set():
                    entries = []
                    for proc in psutil.process_iter(["pid", "name"]):
                        if (proc.info["name"] or "").lower() != "recheck360.exe":
                            continue
                        try:
                            key = (proc.pid, proc.create_time())
                            previous = tracked.get(key)
                            if previous is None:
                                tracked[key] = proc
                                proc.cpu_percent()
                                cpu = None
                            else:
                                proc = previous
                                cpu = proc.cpu_percent()
                            entries.append(dict(pid=proc.pid, cpu_percent_one_core=cpu,
                                                rss_mb=round(proc.memory_info().rss / 1024**2, 2),
                                                threads=proc.num_threads()))
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                    self.samples.append(dict(time=datetime.now().isoformat(timespec="seconds"),
                                             processes=entries))
                    self.stop.wait(1)
            except Exception as exc:
                self.error = type(exc).__name__
        self.thread = threading.Thread(target=collect, daemon=True)
        self.thread.start()

    def finish(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)
        metrics = dict(started_at=self.started, ended_at=datetime.now().isoformat(timespec="seconds"),
                       sampling_error=self.error, samples=self.samples,
                       scope="Desktop observed while backend load generator ran on this same computer; no UI actions were automated.")
        (SUITE_OUTPUT / "desktop_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        if not self.log:
            return dict(component="live_protocol", status="not_available", exit_code=0,
                        error="No desktop application log found.")
        try:
            stat = self.log.stat()
            if stat.st_size < self.offset or (stat.st_dev, stat.st_ino) != self.log_identity:
                raise ValueError("log changed")
            with self.log.open("rb") as handle:
                handle.seek(self.offset)
                lines = handle.read().decode("utf-8", errors="replace").splitlines()
            records, skipped = capture_parse(lines)
            summary = capture_write_report(records, skipped, suite_output("live_protocol"),
                                           self.log, scope="new application log messages during backend load; no diagnostic start was automated")
            return dict(component="live_protocol", status="completed", exit_code=0,
                        recorded_messages=summary["recorded_messages"],
                        note="Zero messages means no observed desktop protocol activity, not a successful diagnostic.")
        except Exception as exc:
            return dict(component="live_protocol", status="failed", exit_code=1, error=type(exc).__name__)


def write_index(outcomes, command):
    failed = any(x["exit_code"] for x in outcomes)
    summary = dict(command=command, component_outcomes=outcomes,
                   execution_status="issues_recorded" if failed else "completed",
                   scope="Component completion does not mean hardware diagnostics passed.",
                   shared_account=True if command in ("all", "dummy", "transport") else None)
    (SUITE_OUTPUT / "suite_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = ["# reCheck360 test suite", "",
             "Run: " + command + ". Execution status: " + summary["execution_status"] + ".", "",
             "| Component | Execution | Detail |", "|---|---|---|"]
    for item in outcomes:
        lines.append("| " + item["component"] + " | " + item["status"] + " | " +
                     str(item.get("error") or item.get("note") or "") + " |")
    dummy_file = suite_output("dummy") / "summary.json"
    if dummy_file.exists():
        data = json.loads(dummy_file.read_text(encoding="utf-8"))
        lines += ["", "## Dummy platform coverage", "",
                  "| Platform | Identities | Connected | Requests | Acknowledged | Failed devices | p95 ms |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for platform, group in data["platforms"].items():
            lines.append(f"| {platform} | {group['dummy_devices']} | {group['connections']} | {group['requests_sent']} | {group['acknowledged_requests']} | {group['failed_devices']} | {group['request_attempt_p95_ms']} |")
    lines += ["", "## Limits", "",
              "- Dummy requests and transport checks use one shared test account and do not execute physical diagnostics.",
              "- Individual result reports analyze saved snapshots; they cannot prove a new run completed.",
              "- Desktop CPU/memory samples do not measure screen latency, freezes, or crash causes.",
              "- Manual observations are included only when an existing CSV is supplied or available.",
              "- Run all does not click desktop controls, start a physical diagnostic, erase phones, or alter device settings.",
              "", "## Files", ""]
    files = [p for p in sorted(SUITE_OUTPUT.rglob("*")) if p.is_file() and p.name not in ("index.html", "README.md")]
    for path in files:
        relative = path.relative_to(SUITE_OUTPUT).as_posix()
        lines.append(f"- [{relative}]({relative})")
    text = "\n".join(lines) + "\n"
    (SUITE_OUTPUT / "README.md").write_text(text, encoding="utf-8")
    links = "".join(f'<li><a href="{html.escape(p.relative_to(SUITE_OUTPUT).as_posix(), quote=True)}">{html.escape(p.relative_to(SUITE_OUTPUT).as_posix())}</a></li>' for p in files)
    body = '<!doctype html><meta charset="utf-8"><title>reCheck360 test results</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:0 20px}pre{white-space:pre-wrap}a{color:#087d72}</style><h1>reCheck360 test results</h1><pre>' + html.escape(text.split("## Files")[0]) + '</pre><h2>Report files</h2><ul>' + links + '</ul>'
    (SUITE_OUTPUT / "index.html").write_text(body, encoding="utf-8")
    print("\nResults: " + str(SUITE_OUTPUT / "index.html"))
    return 1 if failed else 0


def self_test():
    """Offline tests: no staging access and no real desktop/device actions."""
    from unittest.mock import patch
    assert session_percentile([1, 2, 3, 4], .95) == 4
    fixtures = [dummy_fixture(p, n, "self-test") for p in ("ios", "android") for n in range(10)]
    assert len({p["udid"] for p in fixtures}) == 20
    for payload in fixtures:
        reply = dict(payload, status="success")
        assert dummy_classify(reply, payload) == "acknowledged"
        assert dummy_classify(dict(reply, udid="different"), payload) == "mismatched_response"
    plan = [dict(code="A", is_enabled=True), dict(code="B", is_enabled=True)]
    assert not results_evaluate([dict(code="A", result="Pass")], plan)["reported_required_results_complete"]
    report = results_evaluate([dict(code="A", result="Pass"), dict(code="B", result="Fail")], plan)
    assert report["reported_required_results_complete"] and not report["all_required_reported_pass"]
    assert not report["fresh_diagnostic_run_verified"]
    lines = ['2026-09-10 00:00:00.000 [x] DEBUG r.utils.WebSocketManager - Message sent: {"messagetype":4,"udid":"PRIVATE","token":"SECRET","client_data":{"ref":1}}',
             '2026-09-10 00:00:00.125 [x] DEBUG r.utils.WebSocketManager - Received message: {"messagetype":4,"udid":"PRIVATE","status":"success","client_data":{"ref":1}}']
    records, skipped = capture_parse(lines)
    exchanges, _ = capture_analyze(records)
    assert skipped == 0 and exchanges[0]["duration_ms"] == 125
    assert "PRIVATE" not in json.dumps(records) and "SECRET" not in json.dumps(records)

    class FakeResponse:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def json(self): return {"token": "test-token"}
    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, *a, **kw): return FakeResponse()
    class FakeSocket:
        def send(self, raw):
            payload = json.loads(raw)
            self.queue = ["unsolicited text", json.dumps({"messagetype": 99}),
                          json.dumps(dict(payload, status="success"))]
        def recv(self): return self.queue.pop(0)
        def settimeout(self, *a): pass
        def close(self, *a, **kw): pass
    fake_ws = types.SimpleNamespace(create_connection=lambda *a, **kw: FakeSocket(),
                                    WebSocketBadStatusException=type("FakeBadStatus", (Exception,), {}))
    global SUITE_OUTPUT, SUITE_CONFIG
    old_output, old_config = SUITE_OUTPUT, SUITE_CONFIG
    try:
        with tempfile.TemporaryDirectory(prefix="recheck-suite-test-") as folder:
            SUITE_OUTPUT = Path(folder)
            SUITE_CONFIG = dict(LOGIN_URL="http://test", WS_URL="ws://test", USERNAME="test", PASSWORD="test")
            with patch.dict(globals(), requests=types.SimpleNamespace(Session=FakeSession), websocket=fake_ws):
                outcome = run_component("dummy", dummy_main, ["--per-platform", "10", "--rounds", "1", "--spawn-rate", "1000"])
            assert outcome["exit_code"] == 0
            data = json.loads((suite_output("dummy") / "summary.json").read_text())
            assert data["peak_connections"] == 20
            for group in data["platforms"].values():
                assert group["acknowledged_requests"] == 10 and group["background_messages"] == 20
                assert group["failed_devices"] == 0 and group["diagnostics_completed"] == 0
            blank = SUITE_OUTPUT / "observations.csv"
            with blank.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=observation_FIELDS)
                writer.writeheader()
                writer.writerows({"user_id":f"user-{i}"} for i in range(20))
            manual = observation_generate(blank, suite_output("manual"), 20)
            assert manual["observed_devices"] == 0 and manual["successful_journeys"] == 0
            assert write_index([outcome], "self-test") == 0
            assert (SUITE_OUTPUT / "index.html").exists()
    finally:
        SUITE_OUTPUT, SUITE_CONFIG = old_output, old_config
    print("PASS: standalone fixtures, 20 concurrent mock sessions, asynchronous replies, result coverage, redaction, timing, blank observations and report index.")
    return 0


def suite_main():
    parser = argparse.ArgumentParser(description="One-file reCheck360 load testing and diagnostic reporting.")
    parser.add_argument("command", nargs="?", choices=["all", "dummy", "transport", "capture", "results", "observe-init", "observe-report", "self-test"])
    parser.add_argument("--per-platform", type=int, default=10, help="Dummy identities per platform, 1..10 (default 10).")
    parser.add_argument("--rounds", type=int, default=12, help="Dummy requests per identity, 1..12.")
    parser.add_argument("--spawn-rate", type=float, default=2)
    parser.add_argument("--users", type=int, default=20, help="Transport sessions, 1..20.")
    parser.add_argument("--hold", type=int, default=60, help="Transport hold seconds.")
    parser.add_argument("--watch-seconds", type=int, default=180, help="Standalone capture duration; use 0 for historical logs.")
    parser.add_argument("--devices", type=int, default=20, help="Manual observation row count.")
    parser.add_argument("--csv", type=Path, help="Manual observation CSV.")
    parser.add_argument("--log", type=Path, help="reCheck360 application log.")
    parser.add_argument("--output-root", type=Path, default=SUITE_HOME / "reports")
    parser.add_argument("--exclude-code", action="append", default=[], help="Explicitly confirmed non-applicable test code.")
    parser.add_argument("--login-url")
    parser.add_argument("--ws-url")
    parser.add_argument("--username")
    args = parser.parse_args()
    if args.command is None:
        if not sys.stdin.isatty():
            parser.print_help()
            return 0
        choices = {"1":"all", "2":"dummy", "3":"transport", "4":"capture", "5":"results",
                   "6":"observe-init", "7":"observe-report", "8":"self-test"}
        print("reCheck360 testing\n1. Run all: backend load + desktop monitoring + reports\n2. Dummy devices: 10 iOS + 10 Android\n3. Login/WebSocket connection load\n4. Live diagnostic log capture (3 minutes)\n5. Analyze individual saved diagnostic results\n6. Create 20-device observation sheet\n7. Report an observation sheet\n8. Offline self-test\n0. Exit")
        choice = input("Choose an option: ").strip()
        if choice == "0":
            return 0
        if choice not in choices:
            parser.error("Choose a menu option from 0 through 8.")
        args.command = choices[choice]
    if args.command == "self-test":
        return self_test()
    if not 1 <= args.per_platform <= 10 or not 1 <= args.rounds <= 12 or not 1 <= args.users <= 20:
        parser.error("Use 1..10 per platform, 1..12 rounds and 1..20 transport users.")
    if args.spawn_rate <= 0 or not math.isfinite(args.spawn_rate) or args.hold < 5 or args.watch_seconds < 0 or args.devices < 1:
        parser.error("Invalid duration, device count or spawn rate.")
    if args.command in ("all", "dummy", "transport"):
        configure_network(args)
    source = latest_log(args.log)
    if args.command in ("capture", "results") and source is None:
        raise ValueError("No reCheck360 log found. Supply --log or start the desktop application.")
    global SUITE_OUTPUT
    SUITE_OUTPUT = args.output_root.resolve() / datetime.now(timezone.utc).strftime("suite-%Y%m%dT%H%M%S%fZ")
    SUITE_OUTPUT.mkdir(parents=True)
    print("Output folder: " + str(SUITE_OUTPUT), flush=True)
    outcomes = []
    monitor = DesktopMonitor(source) if args.command in ("all", "dummy", "transport") else None
    if monitor:
        monitor.start()
    try:
        if args.command in ("all", "transport"):
            outcomes.append(run_component("transport", session_main,
                ["--users", str(args.users), "--hold", str(args.hold), "--spawn-rate", str(args.spawn_rate)]))
        if args.command in ("all", "dummy"):
            outcomes.append(run_component("dummy", dummy_main,
                ["--per-platform", str(args.per_platform), "--rounds", str(args.rounds), "--spawn-rate", str(args.spawn_rate)]))
        if args.command == "capture":
            outcomes.append(run_component("capture", capture_main,
                ["--log", str(source), "--watch-seconds", str(args.watch_seconds), "--output", str(suite_output("capture"))]))
        if args.command in ("all", "results"):
            if source:
                options = ["--log", str(source), "--output", str(suite_output("diagnostic_results"))]
                for code in args.exclude_code:
                    options += ["--exclude-code", code]
                outcomes.append(run_component("diagnostic_results", results_main, options))
            else:
                outcomes.append(dict(component="diagnostic_results", status="not_available", exit_code=0,
                                     error="No desktop log; backend tests do not create one."))
        observation_csv = args.csv or SUITE_HOME / "device_observations.csv"
        if args.command == "observe-init":
            destination = args.csv or suite_output("device_observations.csv")
            outcomes.append(run_component("observation_sheet", observation_main,
                ["--init", "--csv", str(destination), "--devices", str(args.devices)]))
        if args.command == "observe-report" or (args.command == "all" and observation_csv.exists()):
            if not observation_csv.exists():
                outcomes.append(dict(component="observations", status="failed", exit_code=1,
                                     error="Observation CSV not found; use observe-init first."))
            else:
                outcomes.append(run_component("observations", observation_main,
                    ["--csv", str(observation_csv), "--devices", str(args.devices), "--output", str(suite_output("observations"))]))
        elif args.command == "all":
            outcomes.append(dict(component="observations", status="not_available", exit_code=0,
                                 error="No observation CSV supplied; use observe-init to create one."))
    except KeyboardInterrupt:
        outcomes.append(dict(component="run", status="interrupted", exit_code=130, error="Stopped by user"))
    finally:
        if monitor:
            outcomes.append(monitor.finish())
    return write_index(outcomes, args.command)


if __name__ == "__main__":
    try:
        raise SystemExit(suite_main())
    except ValueError as exc:
        print("Configuration error: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
