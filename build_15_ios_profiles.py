"""Generate one user's 15 iOS fixtures with the user's encoder; no network traffic."""
import base64
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import uuid
import zipfile
from replay_supplied_messages import load_source,SOURCE,write_csv

ROOT=Path(__file__).resolve().parent
DESKTOP=Path(r'C:\Users\usama\OneDrive\Desktop')


def main():
    source=load_source(SOURCE)
    battery_template=json.loads((DESKTOP/'input.txt').read_text(encoding='utf-8-sig'))
    original_hashes={name:hashlib.sha256((DESKTOP/name).read_bytes()).hexdigest() for name in ('input.txt','output.txt')}
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out=ROOT/'profiles'/('one-user-15-ios-'+stamp)
    out.mkdir(parents=True)
    device_steps=[step['payload'] for step in source if step['payload']['messagetype'] not in (134,119)]
    info=plistlib.loads(base64.b64decode(next(p['device_info'] for p in device_steps if p['messagetype']==1)))
    battery_source=json.loads(base64.b64decode(next(c['response'] for p in device_steps if p['messagetype']==4 for c in p['command'] if c['cmd_id']==56)))
    profiles=[]; inventory=[]
    for index in range(1,16):
        identity=uuid.uuid5(uuid.NAMESPACE_URL,f'{stamp}/ios/{index}').hex.upper()
        udid=identity[:8]+'-'+identity[8:24]
        serial='QA'+identity[:10]
        battery_serial='QAB'+identity[10:24]
        name=f'user-01-iOS-{index:02d}'
        folder=out/name; folder.mkdir()
        battery=dict(battery_template,serial_number=battery_serial)
        input_path=folder/'battery_input.json'; encoded_path=folder/'battery_encoded.txt'
        input_path.write_text(json.dumps(battery,indent=2)+'\n',encoding='utf-8')
        subprocess.run([str(DESKTOP/'encoder.exe'),str(input_path),str(encoded_path)],cwd=DESKTOP,check=True,capture_output=True,timeout=20)
        (folder/'input.txt').write_bytes(input_path.read_bytes())
        (folder/'output.txt').write_bytes(encoded_path.read_bytes())
        encoded=encoded_path.read_text(encoding='utf-8-sig').strip()
        assert base64.b64decode(encoded,validate=True)==input_path.read_bytes(), 'Encoder round-trip mismatch'
        replacements={info['UniqueDeviceID']:udid,info['SerialNumber']:serial,battery_source['serial_number']:battery_serial}
        # Also distinguish part serials, IMEIs and MAC addresses found in this recorded source.
        def collect(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if isinstance(item,str) and item and ('serial' in key.lower() or 'internationalmobileequipmentidentity' in key.lower() or key in ('BluetoothAddress','WiFiAddress','EthernetAddress')):
                        if item not in replacements:
                            unique=uuid.uuid5(uuid.NAMESPACE_URL,identity+'/'+item).hex.upper()
                            if 'internationalmobileequipmentidentity' in key.lower(): replacements[item]='99'+str(int(unique[:12],16)).zfill(13)[-13:]
                            elif key.endswith('Address'): replacements[item]='02:'+':'.join(unique[n:n+2] for n in range(0,10,2))
                            else: replacements[item]='QA'+unique[:max(8,min(len(item)-2,24))]
                    collect(item)
            elif isinstance(value,list):
                for item in value: collect(item)
        collect(info)
        def replace(value):
            if isinstance(value,dict): return {k:replace(v) for k,v in value.items()}
            if isinstance(value,list): return [replace(v) for v in value]
            if isinstance(value,bytes):
                for old,new in replacements.items(): value=value.replace(old.encode(),new.encode())
                return value
            if isinstance(value,str):
                for old,new in replacements.items(): value=value.replace(old,new)
            return value
        payloads=json.loads(json.dumps(device_steps))
        for payload in payloads:
            payload.update(replace(payload))
            payload['client_data']={'ref':uuid.uuid4().int >> 76}
            if 'device_info' in payload:
                decoded=replace(plistlib.loads(base64.b64decode(payload['device_info'])))
                decoded['DeviceName']=name
                payload['device_info']=base64.b64encode(plistlib.dumps(decoded)).decode()
                (folder/'device_info_decoded.plist').write_bytes(plistlib.dumps(decoded))
            for command in payload.get('command',[]):
                raw=base64.b64decode(command['response'])
                if command['cmd_id']==56:
                    command['response']=encoded
                    continue
                if raw.lstrip().startswith(b'<?xml'):
                    decoded=replace(plistlib.loads(raw))
                    if command['cmd_id']==5:
                        registry=decoded.get('IORegistry',{})
                        registry['CycleCount']=battery['cycle_count']
                        data=registry.get('BatteryData',{})
                        data['DesignCapacity']=battery['design_capacity']
                        data['NominalChargeCapacity']=battery['current_capacity']
                        data['FullChargeCapacity']=battery['current_capacity']
                    raw=plistlib.dumps(decoded)
                else:
                    raw=replace(raw)
                command['response']=base64.b64encode(raw).decode()
            # Validate identity at every request and within all decoded outputs.
            assert payload['udid']==udid
            for command in payload.get('command',[]):
                assert info['UniqueDeviceID'] not in command['cmd']
                decoded_raw=base64.b64decode(command['response'])
                for old in (info['UniqueDeviceID'],info['SerialNumber'],battery_source['serial_number']):
                    assert old.encode() not in decoded_raw
        profile=dict(user='user-01',device_name=name,platform='ios',model='iPhone 17 Pro Max (simulated)',udid=udid,
                     device_serial=serial,battery=battery,requests=payloads)
        (folder/'profile.json').write_text(json.dumps(profile,indent=2),encoding='utf-8')
        profiles.append(profile)
        inventory.append(dict(user='user-01',device_name=name,platform='ios',udid=udid,device_serial=serial,
                              battery_serial=battery_serial,design_capacity=battery['design_capacity'],current_capacity=battery['current_capacity'],
                              battery_health=battery['battery_health'],cycle_count=battery['cycle_count'],is_analytics=battery['is_analytics'],
                              encoder_verified=True))
    assert len({p['udid'] for p in profiles})==15
    assert len({p['device_serial'] for p in profiles})==15
    assert len({p['battery']['serial_number'] for p in profiles})==15
    for name,value in original_hashes.items(): assert hashlib.sha256((DESKTOP/name).read_bytes()).hexdigest()==value
    write_csv(out/'devices.csv',inventory,list(inventory[0]))
    (out/'profiles.json').write_text(json.dumps(dict(users=1,ios_devices=15,android_devices=0,
        session_requests=[s['payload'] for s in source if s['payload']['messagetype'] in (134,119)],devices=profiles),indent=2),encoding='utf-8')
    (out/'README.txt').write_text(
        'One user, 15 simulated iOS profiles. No staging calls or hardware commands executed.\n'
        'Battery files were encoded with the supplied Desktop encoder.exe and all 15 outputs decoded back to the exact input bytes.\n'
        'Original Desktop input.txt and output.txt are unchanged (SHA256 verified).\n'
        'devices.csv lists identities and battery values; each device folder has battery_input.json, battery_encoded.txt, device_info_decoded.plist and profile.json.\n'
        'profiles.json includes session request templates (134,119) and nine device requests (139,1,2,3,4,5,6,7,8) per profile. Refs must be refreshed on reuse.\n'
        'Device UDID, device serial and battery serial are synthetic and consistently replaced in requests, command arguments and decoded outputs.\n'
        'The user-provided battery values are intentionally preserved: design 2030, current 3720, health 80, cycles 260, analytics true. Current capacity exceeds design capacity. These are unusual-data fixtures, not physically consistent measurements.\n'
        'Other historic measurements, part records, warnings and command errors remain from the source. Empty OEM outputs and SIM-lock file errors are not repaired by encoding.\n'
        'Encoding success does not guarantee backend acceptance or real hardware results. These templates replay recorded outputs; returned command lists may change.\n',encoding='utf-8')
    (out/'all_15_battery_inputs.json').write_text(json.dumps({p['device_name']:p['battery'] for p in profiles},indent=2),encoding='utf-8')
    with zipfile.ZipFile(out.with_suffix('.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
        for path in out.rglob('*'):
            if path.is_file(): archive.write(path,path.relative_to(out))
    print('Created:',out)
    print('ZIP:',out.with_suffix('.zip'))
    print('Verified: 15 unique UDIDs, device serials, battery serials; 15 encoder round trips; original files unchanged; no network requests.')


if __name__=='__main__': main()
