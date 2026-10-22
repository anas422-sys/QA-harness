r"""2 shared-account WebSocket sessions, 10 synthetic devices each; no USB commands.
Run: python run_20_devices.py
Uses local locustfile.py staging credentials; no helper scripts required.
"""
import argparse
import ast
import math
import csv
import hashlib
import base64
import plistlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import threading
import time
import uuid
import requests
import websocket

ROOT = Path(__file__).resolve().parent
REFERENCE = Path(r'C:\Users\usama\.codex\attachments\6869d72b-4be8-4393-a97d-029862798259\pasted-text.txt')



EXCLUDED = {18: 'logout can invalidate shared account sessions', 134: 'session creation changes application state'}
DYNAMIC = {'token','hub_token','access_token','current_date','timestamp','expires_at','client_data','udid','username'}
def settings():
    tree = ast.parse((ROOT/'locustfile.py').read_text(encoding='utf-8-sig'))
    names = {'LOGIN_URL','WS_URL','USERNAME','PASSWORD'}
    result = {n.targets[0].id:ast.literal_eval(n.value) for n in ast.walk(tree) if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in names}
    if set(result)!=names: raise ValueError('Missing staging settings in locustfile.py')
    return result

def percentile(values,fraction):
    return round(sorted(values)[max(0,math.ceil(len(values)*fraction)-1)],2) if values else None


def fixture(platform, number, run_id):
    identity = uuid.uuid5(uuid.NAMESPACE_URL, f"recheck-load/{run_id}/{platform}/{number}").hex
    if platform == "ios":
        udid = identity[:8].upper()+"-"+identity[8:24].upper()
        info = dict(UniqueDeviceID=udid, SerialNumber="QA"+identity[:10].upper(),
                    DeviceName=f"QA simulated iOS {number}", DeviceClass="iPhone",
                    ProductType="iPhone13,1", ProductVersion="18.0",
                    ModelNumber="QA_TEST", HardwareModel="D52gAP",
                    ActivationState="Activated")
        encoded = plistlib.dumps(info, fmt=plistlib.FMT_XML)
    else:
        udid = "QAANDROID"+identity[:12].upper()
        # Exploratory Android fixture; the actual Android wire schema is not supplied.
        info = dict(serial=udid, manufacturer="QA", model="Simulated Android",
                    android_version="14", device_name=f"QA simulated Android {number}")
        encoded = json.dumps(info).encode()
    return dict(client_data={"ref": int(identity[:12],16)}, messagetype=1, udid=udid,
                device_operating_system=platform, operating_system="windows",
                device_info=base64.b64encode(encoded).decode())

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

def redact(value):
    if isinstance(value, dict):
        return {k: '[REDACTED]' if any(s in k.lower() for s in ('token', 'password', 'authorization', 'secret')) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def export_exchange_details(out):
    """Join each measured request with the actual wire messages; preserve extras in messages.csv."""
    csv.field_size_limit(16 * 1024 * 1024)
    def read(name):
        with (out/name).open(encoding='utf-8-sig',newline='') as handle:
            return list(csv.DictReader(handle))
    messages = read('messages.csv')
    requests_rows = read('requests.csv')
    grouped = {}
    for message in messages:
        key = (message['user'],message['message_type'],message['ref'])
        grouped.setdefault(key,[]).append(message)
    pairs = []
    for row in requests_rows:
        if not row['ref']:
            continue
        wire_rows = grouped.get((row['user'],row['message_type'],row['ref']),[])
        outgoing = [m for m in wire_rows if m['direction']=='Message sent']
        incoming = [m for m in wire_rows if m['direction']=='Received message']
        pairs.append(dict(row,sent_at=outgoing[0]['timestamp'] if outgoing else '',
                          received_at=incoming[0]['timestamp'] if incoming else '',
                          sent_json=outgoing[0]['json'] if outgoing else '',
                          received_json=json.dumps([json.loads(m['json']) for m in incoming],ensure_ascii=False)))
    fields = list(pairs[0]) if pairs else ['user','device_name','platform','sent_json','received_json']
    csv_file(out/'sent_received_pairs.csv',pairs,fields)
    manifest = json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    platform_rows = read('platform_summary.csv')
    device_rows = read('device_results.csv')
    errors = read('server_errors.csv')
    lines = ['# Two sessions / 20 simulated devices', '',
             'Same staging service; two sessions share one account. Each has five Android and five iOS devices.',
             'Device labels identify simulated fixtures, not physical phones. No returned shell command was executed.', '',
             '## Device message results', '',
             '| Platform | Assigned | Acknowledged devices | Requests | Acknowledgments | p95 acknowledgment ms | Outcomes |',
             '|---|---:|---:|---:|---:|---:|---|']
    for row in platform_rows:
        lines.append('| '+' | '.join(str(row[k]) for k in ('platform','assigned_devices','acknowledged_unique_devices','requests','acks','p95_ack_ms','outcomes'))+' |')
    lines += ['', '## Every device', '', '| User | Device name | Platform | Model | OS | UDID | Acks | Failures |', '|---|---|---|---|---|---|---:|---:|']
    for row in device_rows:
        lines.append('| '+' | '.join(str(row[k]) for k in ('user','device_name','platform','model','os_version','udid','acknowledgments','failures'))+' |')
    lines += ['', '## Server errors', '']
    lines += [f"- Type {row['message_type']}: {row['server_message']} ({row['count']} replies)" for row in errors] or ['No correlated application-error replies.']
    lines += ['', '## Files and interpretation', '',
              '- `messages_readable.log`: complete captured JSON in readable sent/received form; no ellipses or shortened payloads.',
              '- `messages.log`: one timestamped JSON message per line in the reference log format, with device labels.',
              '- `devices/`: separate readable log for every device that exchanged messages.',
              '- `messages.csv`: every captured WebSocket message, including uncorrelated frames.',
              '- `sent_received_pairs.csv`: full sent JSON and received JSON beside measured outcomes and response times.',
              '- `assigned_devices.csv`: names, platforms, models, OS versions, UDIDs and decoded fixture information.',
              '- `requests.csv`, `device_results.csv`, `user_summary.csv`, `platform_summary.csv`, `stage_summary.csv`: measurements and aggregates.',
              '', 'ACK_ONLY means a correlated success envelope, not verified hardware results. Android fixtures are exploratory. Model and OS columns describe submitted fixtures; full server-returned details are preserved in the message logs.',
              'Startup checks compare 25 reference variants per session. Schema/value differences require review and are separate from device acknowledgment results. Authentication secrets are redacted; business data may remain in local logs.',
              'No UI responsiveness, physical USB behavior, device diagnostic completion or human experience was measured. CSV percentiles cover successful acknowledgments only.',
              '', 'Overall measured outcomes: `'+json.dumps(manifest.get('outcomes',{}))+'`.']
    (out/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-log', type=Path, default=REFERENCE)
    parser.add_argument('--timeout', type=float, default=15)
    parser.add_argument('--pause', type=float, default=10)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if not 0 < args.timeout <= 60 or not 0 <= args.pause <= 60:
        parser.error('timeout must be 0..60 seconds; pause 0..60')
    contracts, gaps = build_reference(args.reference_log)
    if not contracts:
        parser.error('No reference contracts found')
    cfg = settings()
    if 'staging.phone-diagnostics.com/' not in cfg['LOGIN_URL'] or 'staging.phone-diagnostics.com/' not in cfg['WS_URL']:
        parser.error('This harness is restricted to the configured staging service')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = ROOT / 'reports' / ('2-users-20-devices-' + stamp)
    out.mkdir(parents=True)
    devices = {}
    inventory = []
    for user in range(1, 3):
        label = f'user-{user:02d}'
        devices[label] = []
        for slot in range(10):
            platform = 'ios' if slot % 2 == 0 else 'android'
            payload = fixture(platform, (user-1)*10+slot, stamp)
            name = f'{label}-{"iOS" if platform == "ios" else "Android"}-{slot//2+1:02d}'
            decoded = plistlib.loads(base64.b64decode(payload['device_info'])) if platform == 'ios' else json.loads(base64.b64decode(payload['device_info']))
            decoded['DeviceName' if platform == 'ios' else 'device_name'] = name
            payload['device_info'] = base64.b64encode(plistlib.dumps(decoded) if platform == 'ios' else json.dumps(decoded).encode()).decode()
            devices[label].append(payload)
            inventory.append(dict(user=label, slot=slot+1, device_name=name, platform=platform, udid=payload['udid'],
                                  model='iPhone 12 mini (simulated)' if platform=='ios' else 'Simulated Android',
                                  os_version='18.0' if platform=='ios' else '14', decoded_device_info=json.dumps(decoded)))
    by_udid = {d['udid']:d for d in inventory}
    csv_file(out/'assigned_devices.csv', inventory, list(inventory[0]))
    (out/'device_payloads.json').write_text(json.dumps(devices,indent=2),encoding='utf-8')
    (out/'devices').mkdir()
    csv_file(out/'reference_gaps.csv', gaps, ['message_type', 'outcome', 'reason'])
    manifest = dict(users=2, distinct_accounts=1, devices_per_user=10, ios=10, android=10,
                    synthetic=True, reference_variants=len(contracts), stages=[10,10,10],
                    pause_seconds=args.pause, timeout_seconds=args.timeout, prepare_only=args.prepare_only)
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'Output: {out}\nReference variants: {len(contracts)}; devices: {len(inventory)}', flush=True)
    if args.prepare_only:
        return 0
    lock = threading.Lock()
    rows = []
    messages = []
    reference_devices = {}
    active = peak = 0
    ready = [threading.Event() for _ in range(2)]
    stage_barrier = threading.Barrier(2)
    log = (out/'messages.log').open('w', encoding='utf-8', buffering=1)

    def wire(user, direction, value):
        if isinstance(value, (dict, list)):
            text = json.dumps(redact(value), ensure_ascii=False)
        else:
            text = json.dumps({'non_json_frame': '[REDACTED]', 'length': len(value)})
        now = datetime.now().astimezone().isoformat(timespec='milliseconds')
        obj = value if isinstance(value,dict) else {}
        client_data = obj.get('client_data') if isinstance(obj.get('client_data'),dict) else {}
        ref = client_data.get('ref')
        udid = obj.get('udid','')
        with lock:
            if direction == 'Message sent' and udid:
                reference_devices[(user,str(ref))] = udid
            udid = udid or reference_devices.get((user,str(ref)),'')
            device = by_udid.get(udid,{})
            name = device.get('device_name','SESSION-CONFIGURATION-OR-UNASSIGNED')
            platform = device.get('platform','')
            prefix = f'{now} [{user}] [device={name}] [platform={platform}] DEBUG r.utils.WebSocketManager - {direction}: '
            log.write(prefix+text+'\n')
            messages.append(dict(timestamp=now,user=user,device_name=name,platform=platform,udid=udid,direction=direction,
                                 message_type=obj.get('messagetype',''),ref=ref,json=text))
            if device:
                with (out/'devices'/(name+'.log')).open('a',encoding='utf-8') as handle:
                    handle.write(prefix+json.dumps(redact(value),indent=2,ensure_ascii=False)+'\n\n')

    def record(user, phase, payload, outcome, started, details=''):
        row = dict(timestamp_utc=datetime.now(timezone.utc).isoformat(), user=user, phase=phase,
                   device_name=by_udid.get(payload.get('udid'),{}).get('device_name','SESSION'),
                   platform=payload.get('device_operating_system',''), udid=payload.get('udid',''),
                   message_type=payload.get('messagetype',''), ref=payload.get('client_data',{}).get('ref',''),
                   outcome=outcome, response_ms=round((time.perf_counter()-started)*1000,2), details=details)
        with lock:
            rows.append(row)

    def exchange(ws, user, phase, items):
        ws.settimeout(args.timeout)
        pending = {}
        for template, contract in items:
            payload = json.loads(json.dumps(template))
            ref = uuid.uuid4().int >> 76  # exact JSON integer below 2**53
            payload['client_data'] = {'ref': ref}
            started = time.perf_counter()
            try:
                ws.send(json.dumps(payload))
                wire(user, 'Message sent', payload)
                pending[(payload['messagetype'],ref)] = (payload,contract,started)
            except Exception as exc:
                record(user,phase,payload,'SEND_ERROR',started,type(exc).__name__)
        while pending:
            now = time.perf_counter()
            for key, (payload, contract, started) in list(pending.items()):
                if now-started >= args.timeout:
                    record(user,phase,payload,'TIMEOUT',started,'No correlated response within deadline')
                    del pending[key]
            if not pending:
                break
            ws.settimeout(max(.01, min(start+args.timeout-time.perf_counter() for _,_,start in pending.values())))
            try:
                raw = ws.recv()
                if not raw:
                    raise ConnectionError('closed')
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as exc:
                for payload,_,started in pending.values():
                    record(user,phase,payload,'CONNECTION_ERROR',started,type(exc).__name__)
                return False
            try:
                response = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                response = raw
            wire(user,'Received message',response)
            if not isinstance(response,dict) or not isinstance(response.get('client_data'),dict):
                continue
            key = (response.get('messagetype'),response['client_data'].get('ref'))
            try:
                item = pending.pop(key,None)
            except TypeError:
                continue
            if item is None:
                continue
            payload,contract,started = item
            issue = envelope_issue(response,payload,cfg['USERNAME'])
            if issue:
                outcome,detail = issue
                if outcome == 'APPLICATION_FAILURE' and isinstance(response.get('message'), str):
                    detail += '; server: ' + response['message']
            elif contract is None:
                outcome,detail = 'ACK_ONLY','Device acknowledged; hardware diagnostics not verified'
            else:
                differences = min((compare(s,response.get('reply')) for s in contract['schemas']),key=len)
                outcome = 'SCHEMA_MISMATCH' if differences else 'MATCH' if fingerprint(response.get('reply')) in contract['fingerprints'] else 'VALUE_CHANGED'
                detail = '; '.join(differences[:8])
            record(user,phase,payload,outcome,started,detail)
        return True

    def worker(index):
        nonlocal active, peak
        user = f'user-{index+1:02d}'
        ws = None
        counted = False
        def close_session():
            nonlocal ws, counted, active
            try:
                if ws:
                    ws.close(timeout=1)
            finally:
                ws = None
                if counted:
                    with lock:
                        active -= 1
                    counted = False
        step = 'login'
        started = time.perf_counter()
        try:
            try:
                with requests.post(cfg['LOGIN_URL'],json={'username':cfg['USERNAME'],'password':cfg['PASSWORD']},timeout=args.timeout,allow_redirects=False) as response:
                    if response.status_code != 200:
                        raise RuntimeError(f'HTTP {response.status_code}')
                    body = response.json()
                    nested = body.get('data') or {}
                    token = body.get('token') or body.get('access_token') or nested.get('token') or nested.get('access_token')
                    if not isinstance(token,str) or not token:
                        raise RuntimeError('Missing token')
                record(user,step,{},'PASS',started)
                step = 'connect'
                started = time.perf_counter()
                ws = websocket.create_connection(cfg['WS_URL'],header={'Authorization':'Bearer '+token},timeout=args.timeout)
                with lock:
                    active += 1
                    counted = True
                    peak = max(peak,active)
                record(user,step,{},'PASS',started)
                for contract in contracts:
                    if not exchange(ws,user,'startup',[(contract['payload'],contract)]):
                        close_session()
                        break
            except Exception as exc:
                record(user,step,{},'ERROR',started,str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__)
                if ws:
                    close_session()
            finally:
                ready[index].set()
            for stage, count in enumerate(manifest['stages'],1):
                stage_barrier.wait(timeout=600)
                phase = f'stage-{stage}-{count}-devices-per-user'
                if ws:
                    if not exchange(ws,user,phase,[(p,None) for p in devices[user][:count]]):
                        close_session()
                else:
                    for payload in devices[user][:count]:
                        record(user,phase,payload,'NOT_RUN',time.perf_counter(),'WebSocket unavailable')
                stage_barrier.wait(timeout=600)
                if index == 0:
                    print(f'Completed stage {stage}: {count*2} assigned devices',flush=True)
                time.sleep(args.pause)
        finally:
            ready[index].set()
            close_session()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = []
            for i in range(2):
                jobs.append(pool.submit(worker,i))
                time.sleep(.5)
            for job in jobs:
                job.result()
    finally:
        log.close()
        csv_file(out/'requests.csv',rows,['timestamp_utc','user','phase','device_name','platform','udid','message_type','ref','outcome','response_ms','details'])
        csv_file(out/'messages.csv',messages,['timestamp','user','device_name','platform','udid','direction','message_type','ref','json'])
        with (out/'messages_readable.log').open('w',encoding='utf-8') as handle:
            for message in messages:
                handle.write(f"{message['timestamp']} [{message['user']}] [{message['device_name']}] [{message['platform']}] {message['direction']}:\n")
                handle.write(json.dumps(json.loads(message['json']),indent=2,ensure_ascii=False)+'\n\n')
    summaries = []
    for platform in ('ios','android'):
        subset = [r for r in rows if r['platform']==platform]
        acknowledged = [r for r in subset if r['outcome']=='ACK_ONLY']
        timings = [r['response_ms'] for r in acknowledged]
        summaries.append(dict(platform=platform,assigned_devices=10,attempted_unique_devices=len({r['udid'] for r in subset if r['outcome']!='NOT_RUN'}),
                              acknowledged_unique_devices=len({r['udid'] for r in acknowledged}),requests=len(subset),acks=len(acknowledged),
                              p50_ack_ms=percentile(timings,.5),p95_ack_ms=percentile(timings,.95),p99_ack_ms=percentile(timings,.99),outcomes=json.dumps(dict(Counter(r['outcome'] for r in subset)))))
    csv_file(out/'platform_summary.csv',summaries,list(summaries[0]))
    per_user=[]
    for user in devices:
        selected=[r for r in rows if r['user']==user]
        per_user.append(dict(user=user,assigned_devices=10,acknowledged_unique_devices=len({r['udid'] for r in selected if r['outcome']=='ACK_ONLY'}),outcomes=json.dumps(dict(Counter(r['outcome'] for r in selected)))))
    csv_file(out/'user_summary.csv',per_user,list(per_user[0]))
    device_results = []
    for device in inventory:
        selected = [r for r in rows if r['udid']==device['udid']]
        device_results.append(dict(device, acknowledgments=sum(r['outcome']=='ACK_ONLY' for r in selected),
                                   failures=sum(r['outcome']!='ACK_ONLY' for r in selected),
                                   outcomes=json.dumps(dict(Counter(r['outcome'] for r in selected)))))
    csv_file(out/'device_results.csv',device_results,list(device_results[0]))
    errors = Counter((r['message_type'],re.sub(r'for device \S+\.', 'for device <dummy-id>.',r['details'].split('; server: ',1)[-1]))
                     for r in rows if r['outcome']=='APPLICATION_FAILURE')
    csv_file(out/'server_errors.csv',[dict(message_type=k[0],server_message=k[1],count=v) for k,v in errors.items()],
             ['message_type','server_message','count'])
    stages = []
    for phase in sorted({r['phase'] for r in rows}):
        selected = [r for r in rows if r['phase']==phase]
        acks = [r for r in selected if r['outcome']=='ACK_ONLY']
        stages.append(dict(phase=phase,requests=len(selected),acknowledged_devices=len({r['udid'] for r in acks}),
                           responding_sessions=len({r['user'] for r in acks}),p95_ack_ms=percentile([r['response_ms'] for r in acks],.95),
                           outcomes=json.dumps(dict(Counter(r['outcome'] for r in selected)))))
    csv_file(out/'stage_summary.csv',stages,list(stages[0]))
    manifest.update(peak_open_client_sessions=peak,outcomes=dict(Counter(r['outcome'] for r in rows)))
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (out/'README.txt').write_text('2 sessions share ONE account. 20 synthetic identities; no physical device connections.\nStages: 20, 20, 20 device requests; 60 total planned. Startup reference exchanges run once per session.\nmessages.log contains actual sent/received WebSocket JSON, with credential/token fields redacted. HTTP authentication bodies are not logged. Uncorrelated received messages remain in the log.\nACK_ONLY means correlated success, not verified hardware results or equivalent device-info structure. Android fixtures are exploratory.\nReference compares schemas and stable-value hashes. VALUE_CHANGED requires configuration review. Missing reference messages, logout and session creation are excluded.\nLatency percentiles in platform_summary.csv cover acknowledgments only; inspect failures separately. Sessions are client sockets, not proof of simultaneous server processing.\nNo returned commands, USB diagnostics, erasure or updates are executed. No desktop CPU/UI experience is measured. This bounded load test does not determine maximum server capacity.\n',encoding='utf-8')
    print(json.dumps(manifest,indent=2),flush=True)
    print(json.dumps(summaries,indent=2),flush=True)
    export_exchange_details(out)
    return 1 if any(r['outcome'] not in ('PASS','MATCH','ACK_ONLY') for r in rows) else 0


if __name__ == '__main__':
    raise SystemExit(main())
