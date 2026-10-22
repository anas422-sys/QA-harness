"""Replay ONLY requests in the supplied annotated message list, once, on staging.

python replay_supplied_messages.py
Recorded device command outputs are replayed; no local command is executed.
"""
import argparse
import ast
import base64
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.parse import urlparse
import uuid
import zipfile
import requests
import websocket

ROOT = Path(__file__).resolve().parent
SOURCE = Path(r'C:\Users\usama\.codex\attachments\89504ab3-40e1-4c5d-a432-5974a038771b\pasted-text.txt')


def settings():
    names = {'LOGIN_URL','WS_URL','USERNAME','PASSWORD'}
    tree = ast.parse((ROOT/'locustfile.py').read_text(encoding='utf-8-sig'))
    cfg = {n.targets[0].id:ast.literal_eval(n.value) for n in ast.walk(tree)
           if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in names}
    if cfg.keys() != names:
        raise ValueError('Missing credentials/endpoints in locustfile.py')
    for key, scheme in [('LOGIN_URL','https'),('WS_URL','wss')]:
        url = urlparse(cfg[key])
        if url.hostname != 'staging.phone-diagnostics.com' or url.scheme != scheme:
            raise ValueError('Only the existing staging HTTPS/WSS service is allowed')
    return cfg


def redact(value):
    if isinstance(value,dict):
        return {k:'[REDACTED]' if any(s in k.lower() for s in ('password','token','secret','authorization')) else redact(v) for k,v in value.items()}
    if isinstance(value,list):
        return [redact(v) for v in value]
    return value


def write_csv(path,rows,fields):
    with path.open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({k:"'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v for k,v in row.items()})


def load_source(path):
    messages=[]
    for line_number,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
        if line.lstrip().startswith('{'):
            message,_=json.JSONDecoder().raw_decode(line.lstrip())
            messages.append((line_number,message))
    replies={(m['messagetype'],m['client_data']['ref']):m for _,m in messages if 'status' in m}
    steps=[dict(line=line,payload=m,expected=replies.get((m['messagetype'],m['client_data']['ref'])))
           for line,m in messages if 'status' not in m]
    if [s['payload']['messagetype'] for s in steps] != [134,119,139,1,2,3,4,5,6,7,8]:
        raise ValueError('Expected supplied sequence 134,119,139,1,2,3,4,5,6,7,8; refusing unrelated requests')
    return steps


def differences(expected,actual,path='reply'):
    """Compare all expected fields and values; timestamps are reported separately."""
    if type(expected) is not type(actual):
        return [f'{path}: {type(expected).__name__} -> {type(actual).__name__}']
    if isinstance(expected,dict):
        result=[]
        for key,value in expected.items():
            if key=='current_date': continue
            result.extend([f'{path}.{key}: missing'] if key not in actual else differences(value,actual[key],path+'.'+key))
        return result
    if isinstance(expected,list):
        if path.endswith('.command'):
            expected={str(c.get('cmd_id')):c for c in expected}
            actual={str(c.get('cmd_id')):c for c in actual}
            result=differences(expected,actual,path)
            result.extend(f'{path}.{key}: additional command' for key in actual.keys()-expected.keys())
            return result
        return [] if expected==actual else [f'{path}: list differs (expected {len(expected)}, received {len(actual)})']
    return [] if expected==actual else [f'{path}: value differs']


def command_observations(payload):
    result=[]
    for command in payload.get('command',[]):
        decoded=base64.b64decode(command.get('response',''),validate=True).decode('utf-8',errors='replace')
        flags=[]
        if not decoded.strip(): flags.append('EMPTY_OUTPUT')
        if 'ERROR:' in decoded: flags.append('ERROR_IN_RECORDED_OUTPUT')
        if '"level":"WARN"' in decoded: flags.append('WARNING_IN_RECORDED_OUTPUT')
        result.append(dict(message_type=payload['messagetype'],cmd_id=command['cmd_id'],
                           command=command['cmd'],flags='; '.join(flags),decoded_output=decoded))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=SOURCE)
    parser.add_argument('--timeout',type=float,default=20)
    parser.add_argument('--prepare-only',action='store_true')
    args=parser.parse_args()
    if not 0 < args.timeout <= 120: parser.error('timeout must be 0..120 seconds')
    steps=load_source(args.source)
    cfg=settings()
    out=ROOT/'reports'/('supplied-messages-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    source_commands=[r for step in steps for r in command_observations(step['payload'])]
    write_csv(out/'recorded_command_outputs.csv',source_commands,['message_type','cmd_id','command','flags','decoded_output'])
    manifest=dict(source=str(args.source),mode='recorded iOS message replay',sessions=1,physical_commands_executed=0,
                  planned_message_types=[s['payload']['messagetype'] for s in steps],prepare_only=args.prepare_only,
                  note='Only client_data.ref is refreshed. Device data and recorded command outputs are preserved. HTTP authentication precedes the supplied WebSocket list.')
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Output:',out,flush=True)
    if args.prepare_only: return 0
    messages=[]; results=[]; login_results=[]; ws=None
    handles=[(out/name).open('w',encoding='utf-8',buffering=1) for name in ('messages.log','messages_readable.log')]

    def wire(direction,value):
        timestamp=datetime.now().astimezone().isoformat(timespec='milliseconds')
        obj=redact(value)
        metadata=value if isinstance(value,dict) else {}
        ref=(metadata.get('client_data') or {}).get('ref')
        row=dict(timestamp=timestamp,direction=direction,message_type=metadata.get('messagetype',''),ref=ref,
                 udid=metadata.get('udid',''),json=json.dumps(obj,ensure_ascii=False))
        messages.append(row)
        prefix=f'{timestamp} [session-01] [iOS reference device] DEBUG r.utils.WebSocketManager - {direction}: '
        handles[0].write(prefix+row['json']+'\n')
        handles[1].write(prefix+json.dumps(obj,ensure_ascii=False,indent=2)+'\n\n')

    try:
        started=time.perf_counter()
        with requests.post(cfg['LOGIN_URL'],json={'username':cfg['USERNAME'],'password':cfg['PASSWORD']},timeout=args.timeout,allow_redirects=False) as response:
            if response.status_code!=200: raise RuntimeError(f'Login HTTP {response.status_code}')
            data=response.json(); nested=data.get('data') or {}
            token=data.get('token') or data.get('access_token') or nested.get('token') or nested.get('access_token')
            if not isinstance(token,str) or not token: raise RuntimeError('No login token returned')
        login_results.append(dict(step='HTTP login',outcome='PASS',duration_ms=round((time.perf_counter()-started)*1000,2)))
        started=time.perf_counter()
        ws=websocket.create_connection(cfg['WS_URL'],header={'Authorization':'Bearer '+token},timeout=args.timeout)
        login_results.append(dict(step='WebSocket connect',outcome='PASS',duration_ms=round((time.perf_counter()-started)*1000,2)))
        for step in steps:
            payload=json.loads(json.dumps(step['payload']))
            original_ref=payload['client_data']['ref']
            payload['client_data']['ref']=uuid.uuid4().int >> 76
            ref=payload['client_data']['ref']; kind=payload['messagetype']
            started=time.perf_counter(); reply=None; outcome='TIMEOUT'; detail='No correlated reply within deadline'
            try:
                ws.settimeout(args.timeout)
                ws.send(json.dumps(payload))
                wire('Message sent',payload)
                while time.perf_counter()-started < args.timeout:
                    ws.settimeout(max(.001,args.timeout-(time.perf_counter()-started)))
                    try: raw=ws.recv()
                    except websocket.WebSocketTimeoutException: break
                    if not raw: raise ConnectionError('WebSocket closed')
                    try: message=json.loads(raw)
                    except (ValueError,UnicodeDecodeError):
                        wire('Received message',{'non_json_frame':str(raw)})
                        continue
                    wire('Received message',message)
                    if not isinstance(message,dict): continue
                    if message.get('messagetype')!=kind or not isinstance(message.get('client_data'),dict) or message['client_data'].get('ref')!=ref: continue
                    reply=message
                    if reply.get('status')!='success':
                        outcome='APPLICATION_FAILURE'; detail=str(reply.get('message',reply.get('error','status was not success')))
                    elif reply.get('username',cfg['USERNAME'])!=cfg['USERNAME'] or ('udid' in reply and reply['udid']!=payload.get('udid')):
                        outcome='IDENTITY_MISMATCH'; detail='Returned account/device differs'
                    elif step['expected'] is None:
                        outcome='ACK_NO_REFERENCE'; detail='Successful reply; source contains no response for this type'
                    else:
                        diff=differences(step['expected'].get('reply'),reply.get('reply'))
                        if 'udid' in step['expected'] and 'udid' not in reply: diff.append('udid: missing')
                        if 'username' in step['expected'] and 'username' not in reply: diff.append('username: missing')
                        outcome='REFERENCE_DIFFERENCE' if diff else 'MATCH'
                        detail='; '.join(diff) if diff else 'Expected reply fields/values match, excluding current_date; extra object fields allowed'
                    break
            except Exception as exc:
                outcome='TRANSPORT_ERROR'; detail=type(exc).__name__
            elapsed=round((time.perf_counter()-started)*1000,2)
            results.append(dict(message_type=kind,source_line=step['line'],original_ref=original_ref,ref=ref,udid=payload.get('udid',''),
                                outcome=outcome,response_ms=elapsed,details=detail,
                                recorded_output_flags='; '.join(r['flags'] for r in command_observations(payload) if r['flags']),
                                sent_json=json.dumps(redact(payload)),received_json=json.dumps(redact(reply)) if reply is not None else ''))
            print(f'Type {kind}: {outcome}, {elapsed} ms',flush=True)
        # Capture late/unsolicited frames briefly without issuing any extra request.
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            ws.settimeout(max(.001,deadline-time.monotonic()))
            try:
                raw=ws.recv()
                if not raw: break
                try: message=json.loads(raw)
                except ValueError: message={'non_json_frame':str(raw)}
                wire('Received message',message)
            except (websocket.WebSocketTimeoutException,websocket.WebSocketConnectionClosedException): break
    except Exception as exc:
        login_results.append(dict(step='session failure',outcome=type(exc).__name__,duration_ms='',detail=str(exc) if isinstance(exc,RuntimeError) else 'See outcome'))
        print('Session failure:',type(exc).__name__,flush=True)
    finally:
        if ws:
            try: ws.close(timeout=1)
            except Exception: pass
        for handle in handles: handle.close()
        for step in steps[len(results):]:
            results.append(dict(message_type=step['payload']['messagetype'],outcome='NOT_RUN',details='Session unavailable'))
        write_csv(out/'requests.csv',results,['message_type','source_line','original_ref','ref','udid','outcome','response_ms','details','recorded_output_flags','sent_json','received_json'])
        write_csv(out/'messages.csv',messages,['timestamp','direction','message_type','ref','udid','json'])
        write_csv(out/'authentication.csv',login_results,['step','outcome','duration_ms','detail'])
    manifest.update(sent=sum(m['direction']=='Message sent' for m in messages),received=sum(m['direction']=='Received message' for m in messages),
                    outcomes=dict(Counter(r['outcome'] for r in results)))
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    report=['# Supplied-message replay results','',f"Sent: {manifest['sent']}; received: {manifest['received']} (including unsolicited messages).",'',
            'One staging account/session, one supplied iOS device, one pass. This is a baseline replay, not a capacity/stress measurement.',
            'The exact supplied requests were used in source order, with fresh correlation references. Recorded command outputs were submitted unchanged; no commands were executed.', '',
            '| Type | Outcome | Response ms | Details |','|---|---|---:|---|']
    report += [f"| {r['message_type']} | {r['outcome']} | {r.get('response_ms','')} | {r['details']} |" for r in results]
    report += ['', 'Source command outputs contain empty outputs, a go-ios agent warning and a SIM-lock file error. A successful server envelope does not prove those hardware checks succeeded.',
               'REFERENCE_DIFFERENCE reports content/schema drift, not automatically a defect. current_date is excluded from comparison; additional object fields are allowed.',
               'The file does not contain responses for types 134/119; their success envelopes cannot be compared against a source response.',
               'See messages_readable.log for full sent/received JSON, requests.csv for paired data and timings, and recorded_command_outputs.csv for decoded inputs. Authentication fields are redacted.']
    (out/'RESULTS.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    with zipfile.ZipFile(out.with_suffix('.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
        for path in out.iterdir():
            if path.is_file(): archive.write(path,path.name)
    print(json.dumps(manifest,indent=2),flush=True)
    return 0 if all(r['outcome'] in ('MATCH','ACK_NO_REFERENCE') for r in results) else 1


if __name__=='__main__':
    raise SystemExit(main())
