"""Run the new 15 profiles on one staging session and export a three-column CSV."""
import csv
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import zipfile
from test_one_user_ios import main as run_session
from replay_supplied_messages import write_csv

ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout',type=float,default=40,help='WebSocket reply deadline in seconds (default 40)')
    args=parser.parse_args()
    if not 0 < args.timeout <= 120: parser.error('timeout must be between 0 and 120 seconds')
    source=ROOT/'profiles/one-user-15-ios-20260928T092549548235Z/profiles.json'
    data=json.loads(source.read_text(encoding='utf-8'))
    assert len(data['devices'])==15
    out=ROOT/'reports'/('one-user-15-ios-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    code=run_session(data,out,'user-01',response_timeout=args.timeout)
    csv.field_size_limit(16*1024*1024)
    with (out/'requests.csv').open(encoding='utf-8-sig',newline='') as f: requests=list(csv.DictReader(f))
    rows=[]
    for device in data['devices']:
        selected=[r for r in requests if r['udid']==device['udid']]
        problems=[f"type {r['message_type']}: {r['outcome']}" for r in selected if r['outcome'] not in ('ACK_ONLY','BATTERY_MATCH')]
        battery=any(r['message_type']=='4' and r['outcome']=='BATTERY_MATCH' for r in selected)
        drift=sum(bool(r['command_drift']) for r in selected)
        if len(selected)!=9: problems.append(f'Only {len(selected)}/9 steps recorded')
        if not battery and not any(r['message_type']=='4' and r['outcome'] not in ('ACK_ONLY','BATTERY_MATCH') for r in selected):
            problems.append('Battery match not verified')
        result=('FAIL - '+'; '.join(problems)) if problems else 'PASS WITH WARNINGS - 9/9 replies successful; battery fields matched'
        if drift: result+=f'; {drift} command-list differences'
        result+='; recorded-output replay, hardware not verified'
        rows.append({'Device Name':device['device_name'],'UDID':device['udid'],'Test Run Result':result})
    write_csv(out/'device_test_results.csv',rows,['Device Name','UDID','Test Run Result'])
    assert len(rows)==15 and len({r['UDID'] for r in rows})==15
    with zipfile.ZipFile(out.with_suffix('.zip'),'w',zipfile.ZIP_DEFLATED) as z:
        for path in out.iterdir():
            if path.is_file(): z.write(path,path.name)
    print('DEVICE CSV:',out/'device_test_results.csv',flush=True)
    print('Device outcomes:',json.dumps({'passed_with_warnings':sum(r['Test Run Result'].startswith('PASS') for r in rows),'failed':sum(r['Test Run Result'].startswith('FAIL') for r in rows)}),flush=True)
    return code

if __name__=='__main__': raise SystemExit(main())
