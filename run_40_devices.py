r"""20 shared-account WebSocket sessions, 20 synthetic devices each; no USB commands.
Run: python run_40_devices.py
Requires existing local helper scripts and locustfile.py staging credentials.
"""
import argparse
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
from run_session_load import settings, percentile
from run_dummy_devices import fixture
from validate_message_flow import build_reference, compare, fingerprint, envelope_issue, csv_file

ROOT = Path(__file__).resolve().parent
REFERENCE = Path(r'C:\Users\usama\.codex\attachments\6869d72b-4be8-4393-a97d-029862798259\pasted-text.txt')


def redact(value):
    if isinstance(value, dict):
        return {k: '[REDACTED]' if any(s in k.lower() for s in ('token', 'password', 'authorization', 'secret')) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


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
    out = ROOT / 'reports' / ('400-devices-' + stamp)
    out.mkdir(parents=True)
    devices = {}
    inventory = []
    for user in range(1, 21):
        label = f'user-{user:02d}'
        devices[label] = []
        for slot in range(20):
            platform = 'ios' if slot % 2 == 0 else 'android'
            payload = fixture(platform, (user-1)*20+slot, stamp)
            devices[label].append(payload)
            inventory.append(dict(user=label, slot=slot+1, platform=platform, udid=payload['udid']))
    csv_file(out/'assigned_devices.csv', inventory, ['user', 'slot', 'platform', 'udid'])
    csv_file(out/'reference_gaps.csv', gaps, ['message_type', 'outcome', 'reason'])
    manifest = dict(users=20, distinct_accounts=1, devices_per_user=20, ios=200, android=200,
                    synthetic=True, reference_variants=len(contracts), stages=[5,10,20,20,20],
                    pause_seconds=args.pause, timeout_seconds=args.timeout, prepare_only=args.prepare_only)
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'Output: {out}\nReference variants: {len(contracts)}; devices: {len(inventory)}', flush=True)
    if args.prepare_only:
        return 0
    lock = threading.Lock()
    rows = []
    active = peak = 0
    ready = [threading.Event() for _ in range(20)]
    stage_barrier = threading.Barrier(20)
    log = (out/'messages.log').open('w', encoding='utf-8', buffering=1)

    def wire(user, direction, value):
        if isinstance(value, (dict, list)):
            text = json.dumps(redact(value), ensure_ascii=False)
        else:
            text = json.dumps({'non_json_frame': '[REDACTED]', 'length': len(value)})
        now = datetime.now().astimezone().isoformat(timespec='milliseconds')
        with lock:
            log.write(f'{now} [{user}] DEBUG r.utils.WebSocketManager - {direction}: {text}\n')

    def record(user, phase, payload, outcome, started, details=''):
        row = dict(timestamp_utc=datetime.now(timezone.utc).isoformat(), user=user, phase=phase,
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
                    print(f'Completed stage {stage}: {count*20} assigned devices',flush=True)
                time.sleep(args.pause)
        finally:
            ready[index].set()
            close_session()

    try:
        with ThreadPoolExecutor(max_workers=20) as pool:
            jobs = []
            for i in range(20):
                jobs.append(pool.submit(worker,i))
                time.sleep(.5)
            for job in jobs:
                job.result()
    finally:
        log.close()
        csv_file(out/'requests.csv',rows,['timestamp_utc','user','phase','platform','udid','message_type','ref','outcome','response_ms','details'])
    summaries = []
    for platform in ('ios','android'):
        subset = [r for r in rows if r['platform']==platform]
        acknowledged = [r for r in subset if r['outcome']=='ACK_ONLY']
        timings = [r['response_ms'] for r in acknowledged]
        summaries.append(dict(platform=platform,assigned_devices=200,attempted_unique_devices=len({r['udid'] for r in subset if r['outcome']!='NOT_RUN'}),
                              acknowledged_unique_devices=len({r['udid'] for r in acknowledged}),requests=len(subset),acks=len(acknowledged),
                              p50_ack_ms=percentile(timings,.5),p95_ack_ms=percentile(timings,.95),p99_ack_ms=percentile(timings,.99),outcomes=json.dumps(dict(Counter(r['outcome'] for r in subset)))))
    csv_file(out/'platform_summary.csv',summaries,list(summaries[0]))
    per_user=[]
    for user in devices:
        selected=[r for r in rows if r['user']==user]
        per_user.append(dict(user=user,assigned_devices=20,acknowledged_unique_devices=len({r['udid'] for r in selected if r['outcome']=='ACK_ONLY'}),outcomes=json.dumps(dict(Counter(r['outcome'] for r in selected)))))
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
    (out/'README.txt').write_text('20 sessions share ONE account. 400 synthetic identities; no physical device connections.\nStages: 100, 200, 400, 400, 400 device requests; 1500 total planned. Startup reference exchanges run once per session.\nmessages.log contains actual sent/received WebSocket JSON, with credential/token fields redacted. HTTP authentication bodies are not logged. Uncorrelated received messages remain in the log.\nACK_ONLY means correlated success, not verified hardware results or equivalent device-info structure. Android fixtures are exploratory.\nReference compares schemas and stable-value hashes. VALUE_CHANGED requires configuration review. Missing reference messages, logout and session creation are excluded.\nLatency percentiles in platform_summary.csv cover acknowledgments only; inspect failures separately. Sessions are client sockets, not proof of simultaneous server processing.\nNo returned commands, USB diagnostics, erasure or updates are executed. No desktop CPU/UI experience is measured. This bounded load test does not determine maximum server capacity.\n',encoding='utf-8')
    print(json.dumps(manifest,indent=2),flush=True)
    print(json.dumps(summaries,indent=2),flush=True)
    return 1 if any(r['outcome'] not in ('PASS','MATCH','ACK_ONLY') for r in rows) else 0


if __name__ == '__main__':
    raise SystemExit(main())
