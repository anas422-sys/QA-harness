"""One staging login/socket, 20 generated iOS devices; replay recorded outputs only."""
import base64
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import time
import uuid
import zipfile
import requests
import websocket
from replay_supplied_messages import settings,redact,write_csv

ROOT=Path(__file__).resolve().parent
PROFILES=ROOT/'profiles/one-user-20-ios-20260925T093047677298Z/profiles.json'


def main(data=None, output=None, user='user-01', response_timeout=20):
    if not 0 < response_timeout <= 120:
        raise ValueError('Response timeout must be between 0 and 120 seconds')
    data=data if data is not None else json.loads(PROFILES.read_text(encoding='utf-8')); cfg=settings()
    devices=data['devices']
    assert devices and len({d['udid'] for d in devices})==len(devices)
    for device in devices:
        battery=next(c for p in device['requests'] if p['messagetype']==4 for c in p['command'] if c['cmd_id']==56)
        assert json.loads(base64.b64decode(battery['response']))==device['battery']
    out=output if output is not None else ROOT/'reports'/('one-user-20-ios-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True); print('Output:',out,flush=True)
    rows=[]; messages=[]; assigned={d['udid']:d for d in devices}; refs={}; commands={}; ws=None
    log=(out/'messages_readable.log').open('w',encoding='utf-8',buffering=1)
    def wire(direction,obj):
        meta=obj if isinstance(obj,dict) else {}
        ref=(meta.get('client_data') or {}).get('ref')
        name=refs.get(str(ref),'UNASSIGNED')
        row=dict(timestamp=datetime.now().astimezone().isoformat(timespec='milliseconds'),user=user,device_name=name,
                 direction=direction,message_type=meta.get('messagetype',''),ref=ref,json=json.dumps(redact(obj)))
        messages.append(row)
        log.write(f"{row['timestamp']} [{user}] [{name}] [iOS] {direction}:\n"+json.dumps(redact(obj),indent=2)+'\n\n')
    def record(name,p,started,outcome,detail,reply=None,drift=''):
        rows.append(dict(device_name=name,udid=p.get('udid',''),message_type=p['messagetype'],ref=p['client_data']['ref'],
                         response_ms=round((time.perf_counter()-started)*1000,2),outcome=outcome,details=detail,command_drift=drift,
                         sent_json=json.dumps(redact(p)),received_json=json.dumps(redact(reply)) if reply is not None else ''))
    def batch(items):
        pending={}
        ws.settimeout(response_timeout)
        for name,template in items:
            p=json.loads(json.dumps(template)); p['client_data']={'ref':uuid.uuid4().int>>76}
            ref=p['client_data']['ref']; refs[str(ref)]=name; start=time.perf_counter()
            drift=''
            if p['messagetype'] in (2,4,6,8):
                wanted=commands.get((p['udid'],p['messagetype']-1))
                provided={c['cmd_id'] for c in p['command']}
                if wanted is not None and wanted!=provided:
                    drift=f'Current server requested {sorted(wanted)}; recorded inputs provide {sorted(provided)}'
            try:
                ws.send(json.dumps(p)); wire('Message sent',p)
                pending[(p['messagetype'],ref)]=(name,p,start,drift)
            except Exception as exc: record(name,p,start,'SEND_ERROR',type(exc).__name__,drift=drift)
        while pending:
            for key,(name,p,start,drift) in list(pending.items()):
                if time.perf_counter()-start>=response_timeout:
                    record(name,p,start,'TIMEOUT',f'No correlated reply in {response_timeout:g} seconds',drift=drift); del pending[key]
            if not pending: break
            ws.settimeout(max(.001,min(start+response_timeout-time.perf_counter() for _,_,start,_ in pending.values())))
            try:
                # Return control frames too: recv() can otherwise keep consuming
                # ping/pong frames internally without returning to the deadline check.
                opcode,raw=ws.recv_data(control_frame=True)
                if opcode in (websocket.ABNF.OPCODE_PING,websocket.ABNF.OPCODE_PONG):
                    continue
                if opcode==websocket.ABNF.OPCODE_CLOSE:
                    raise ConnectionError('WebSocket closed')
                if not raw: raise ConnectionError()
            except websocket.WebSocketTimeoutException: continue
            except Exception as exc:
                for name,p,start,drift in pending.values(): record(name,p,start,'CONNECTION_ERROR',type(exc).__name__,drift=drift)
                return
            try: reply=json.loads(raw)
            except ValueError: reply={'non_json_frame':str(raw)}
            wire('Received message',reply)
            if not isinstance(reply,dict) or not isinstance(reply.get('client_data'),dict): continue
            item=pending.pop((reply.get('messagetype'),reply['client_data'].get('ref')),None)
            if not item: continue
            name,p,start,drift=item
            outcome='ACK_ONLY'; detail='Correlated success; not proof of hardware diagnostics'
            if reply.get('status')!='success':
                outcome='APPLICATION_FAILURE'; detail=str(reply.get('message',reply.get('error','Non-success status')))
            elif reply.get('username',cfg['USERNAME'])!=cfg['USERNAME'] or ('udid' in reply and reply['udid']!=p.get('udid')):
                outcome='IDENTITY_MISMATCH'; detail='Account/device mismatch'
            elif p['messagetype']==4:
                battery=assigned[p['udid']]['battery']; actual=reply.get('reply') or {}
                expected={k:battery[k] for k in ('design_capacity','current_capacity','battery_health','cycle_count')}
                expected['battery_serial']=battery['serial_number']
                mismatches={k:{'expected':v,'actual':actual.get(k)} for k,v in expected.items() if actual.get(k)!=v}
                outcome='BATTERY_MISMATCH' if mismatches else 'BATTERY_MATCH'
                detail=json.dumps(mismatches) if mismatches else 'All five returned battery fields match submitted profile; is_analytics is not checked unless returned'
                if 'is_analytics' in actual and actual['is_analytics']!=battery['is_analytics']:
                    outcome='BATTERY_MISMATCH'; detail+='; is_analytics differs'
            if reply.get('status')=='success' and isinstance(reply.get('reply'),dict) and 'command' in reply['reply']:
                commands[(p.get('udid'),p['messagetype'])]={c['cmd_id'] for c in reply['reply']['command']}
            record(name,p,start,outcome,detail,reply,drift)
    failure=''
    try:
        with requests.post(cfg['LOGIN_URL'],json={'username':cfg['USERNAME'],'password':cfg['PASSWORD']},timeout=20,allow_redirects=False) as response:
            if response.status_code!=200: raise RuntimeError(f'Login HTTP {response.status_code}')
            body=response.json(); nested=body.get('data') or {}
            token=body.get('token') or body.get('access_token') or nested.get('token') or nested.get('access_token')
            if not token: raise RuntimeError('Missing token')
        ws=websocket.create_connection(cfg['WS_URL'],header={'Authorization':'Bearer '+token},timeout=20)
        for payload in data['session_requests']: batch([('SESSION',payload)])
        for kind in (139,1,2,3,4,5,6,7,8):
            batch([(d['device_name'],next(p for p in d['requests'] if p['messagetype']==kind)) for d in devices])
            print('Completed type',kind,dict(Counter(r['outcome'] for r in rows if r['message_type']==kind)),flush=True)
    except Exception as exc:
        failure=str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__
        print('Session failed:',failure,flush=True)
    finally:
        if ws:
            try: ws.close(timeout=1)
            except Exception: pass
        log.close()
    expected=[('SESSION',p) for p in data['session_requests']]+[(d['device_name'],p) for d in devices for p in d['requests']]
    completed={(r['device_name'],r['message_type']) for r in rows}
    for name,p in expected:
        if (name,p['messagetype']) not in completed: record(name,p,time.perf_counter(),'NOT_RUN','Session ended before request')
    write_csv(out/'requests.csv',rows,['device_name','udid','message_type','ref','response_ms','outcome','details','command_drift','sent_json','received_json'])
    write_csv(out/'messages.csv',messages,['timestamp','user','device_name','direction','message_type','ref','json'])
    summary=dict(response_timeout_seconds=response_timeout,users=1,user=user,ios_devices=len(devices),planned_requests=len(expected),sent=sum(m['direction']=='Message sent' for m in messages),
                 received=sum(m['direction']=='Received message' for m in messages),outcomes=dict(Counter(r['outcome'] for r in rows)),
                 command_drift_requests=sum(bool(r.get('command_drift')) for r in rows),session_error=failure)
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    report=[f'# {user} / {len(devices)} iOS profile replay','',json.dumps(summary,indent=2),'',
            f'One login, one WebSocket. Two session requests, then nine message types for each of {len(devices)} devices. Each step sends its device requests before receiving their replies.',
            'BATTERY_MATCH checks battery serial, design capacity, current capacity, health and cycles against the changed profile. Other success responses are ACK_ONLY, not full data validation.',
            'New UDIDs may have no saved information for type 139. Application errors are preserved, not counted as success.',
            'Recorded outputs are replayed even if current server command IDs differ; command_drift lists these differences. No hardware commands are executed.',
            'The supplied current capacity 3720 exceeds design capacity 2030; health 80 does not reconcile with that ratio. These are intentionally unusual test values, not realistic measurements.',
            'Source OEM warnings, empty command outputs and SIM-lock errors remain in the fixtures. A success envelope does not prove these checks worked.',
            'See requests.csv for paired full JSON, errors, command-list differences and timings; messages_readable.log contains all captured messages. Authentication fields are redacted.']
    (out/'RESULTS.md').write_text('\n'.join(report),encoding='utf-8')
    with zipfile.ZipFile(out.with_suffix('.zip'),'w',zipfile.ZIP_DEFLATED) as z:
        for p in out.iterdir(): z.write(p,p.name)
    print(json.dumps(summary,indent=2),flush=True)
    return 1 if any(r['outcome'] not in ('ACK_ONLY','BATTERY_MATCH') for r in rows) else 0


if __name__=='__main__': raise SystemExit(main())
