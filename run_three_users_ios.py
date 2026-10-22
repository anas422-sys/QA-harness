"""Three concurrent sessions on the existing account, five iOS fixtures each."""
import base64
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime,timezone
import json
from pathlib import Path
import plistlib
import zipfile
from collections import Counter
from test_one_user_ios import main as run_session,PROFILES,ROOT
from replay_supplied_messages import write_csv


def main():
    original=json.loads(PROFILES.read_text(encoding='utf-8'))
    out=ROOT/'reports'/('3-users-15-ios-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(parents=True)
    assignments=[]; jobs=[]
    print('Combined results:',out,flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for index in range(3):
            user=f'user-{index+1:02d}'
            data=json.loads(json.dumps(original))
            data['devices']=data['devices'][index*5:(index+1)*5]
            for slot,device in enumerate(data['devices'],1):
                device['device_name']=f'{user}-iOS-{slot:02d}'; device['user']=user
                payload=next(p for p in device['requests'] if p['messagetype']==1)
                info=plistlib.loads(base64.b64decode(payload['device_info']))
                info['DeviceName']=device['device_name']
                payload['device_info']=base64.b64encode(plistlib.dumps(info)).decode()
                assignments.append(dict(user=user,device_name=device['device_name'],udid=device['udid'],device_serial=device['device_serial'],battery_serial=device['battery']['serial_number']))
            jobs.append(pool.submit(run_session,data,out/user,user))
        exit_codes=[job.result() for job in jobs]
    assert len({a['udid'] for a in assignments})==15
    write_csv(out/'assigned_devices.csv',assignments,list(assignments[0]))
    csv.field_size_limit(16*1024*1024)
    requests_rows=[]; messages=[]; summaries=[]
    with (out/'messages_readable.log').open('w',encoding='utf-8') as merged:
        for index in range(3):
            user=f'user-{index+1:02d}'; folder=out/user
            summaries.append(json.loads((folder/'summary.json').read_text()))
            merged.write((folder/'messages_readable.log').read_text(encoding='utf-8')+'\n')
            for name,target in [('requests.csv',requests_rows),('messages.csv',messages)]:
                with (folder/name).open(encoding='utf-8-sig',newline='') as handle:
                    for row in csv.DictReader(handle): target.append(dict(row,user=user))
    write_csv(out/'requests.csv',requests_rows,list(requests_rows[0]))
    write_csv(out/'messages.csv',messages,list(messages[0]) if messages else ['user','direction'])
    summary=dict(users=3,distinct_accounts=1,devices_per_user=5,ios_devices=15,planned_requests=141,
                 sent=sum(s['sent'] for s in summaries),received=sum(s['received'] for s in summaries),
                 outcomes=dict(Counter(r['outcome'] for r in requests_rows)),
                 command_drift_requests=sum(s['command_drift_requests'] for s in summaries),sessions=summaries)
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    report=['# Three sessions, five iOS devices each','',
            'Three concurrent client sessions share the existing staging account. The first 15 existing generated device identities are reused; five unique identities are assigned to each session. No physical commands execute.',
            'Each session performs 134 and 119 once, followed by device types 139,1,2,3,4,5,6,7,8. There are 141 planned requests total.',
            'Raw recorded outputs are submitted even where current command lists differ; these differences are recorded and this is not a hardware-equivalent diagnostic run.',
            'Battery values remain the supplied unusual values. BATTERY_MATCH checks the five returned fields against submitted values. Other successes are ACK_ONLY.',
            'messages_readable.log is grouped by session, with timestamps on every entry. messages.csv can be sorted chronologically.',
            '',json.dumps(summary,indent=2)]
    (out/'RESULTS.md').write_text('\n'.join(report),encoding='utf-8')
    with zipfile.ZipFile(out.with_suffix('.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
        for path in out.rglob('*'):
            if path.is_file() and path.suffix!='.zip': archive.write(path,path.relative_to(out))
    print('FINAL:',json.dumps(summary,indent=2),flush=True)
    return max(exit_codes)


if __name__=='__main__': raise SystemExit(main())
