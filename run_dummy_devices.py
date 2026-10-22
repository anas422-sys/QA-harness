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
import requests
import websocket
from run_session_load import settings, percentile

ROOT = Path(__file__).resolve().parent


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


def sanitized(value, key="", depth=0):
    if depth > 4:
        return "<nested>"
    if isinstance(value,dict):
        return {k: sanitized(v,k,depth+1) for k,v in list(value.items())[:40]}
    if isinstance(value,list):
        return {"list_count":len(value),"first_shape":sanitized(value[0],depth=depth+1) if value else None}
    if isinstance(value,(bool,int,float)) or value is None:
        return value
    # Only expose short protocol result fields; all other strings are redacted.
    if key.lower() in ("status","error","message","detail","code","messagetype") and isinstance(value,str):
        text = value[:240]
        if any(word in text.lower() for word in ("token","password","bearer")):
            return "<redacted>"
        return text
    return "<string>"


def classify(reply, payload):
    # Conservatively distinguish explicit rejection from an unvalidated response.
    if not isinstance(reply,dict):
        return "unvalidated_response"
    status = reply.get("status")
    if (isinstance(status,str) and status.lower() in ("error","failed","failure","rejected")) or reply.get("success") is False or reply.get("error"):
        return "rejected"
    if reply.get("udid") != payload["udid"] or reply.get("client_data",{}).get("ref") != payload["client_data"]["ref"] or reply.get("messagetype") != payload["messagetype"]:
        return "mismatched_response"
    if status == "success":
        return "acknowledged"
    return "unvalidated_response"


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--per-platform",type=int,default=1)
    parser.add_argument("--rounds",type=int,default=12)
    parser.add_argument("--spawn-rate",type=float,default=2)
    args=parser.parse_args()
    if not 1 <= args.per_platform <= 10 or not 1 <= args.rounds <= 12 or args.spawn_rate <= 0:
        parser.error("per-platform must be 1..10 and rounds 1..12")
    cfg=settings()
    run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out=ROOT/"reports"/("dummy-"+run_id)
    out.mkdir(parents=True)
    devices=[dict(platform=p,device_id=f"{p}-{n:02d}",payload=fixture(p,n,run_id))
             for n in range(1,args.per_platform+1) for p in ("ios","android")]
    ready={d["device_id"]:threading.Event() for d in devices}
    go=threading.Event()
    lock=threading.Lock()
    active=peak=0
    events=[]
    def worker(device):
        nonlocal active,peak
        ws=None
        connected=False
        result=dict(platform=device["platform"],device_id=device["device_id"],
                    dummy_udid=device["payload"]["udid"],login_ok=False,connection_ok=False,
                    requests_sent=0,replies_received=0,acknowledged_requests=0,background_messages=0,diagnostics_completed=0,
                    outcomes=[],response_samples=[])
        step="login"
        started=time.perf_counter()
        def event(outcome):
            with lock:
                events.append(dict(platform=device["platform"],device_id=device["device_id"],
                                   step=step,outcome=outcome,duration_ms=round((time.perf_counter()-started)*1000,2)))
        try:
            with requests.Session() as client:
                with client.post(cfg["LOGIN_URL"],json={"username":cfg["USERNAME"],"password":cfg["PASSWORD"]},
                                 timeout=15,allow_redirects=False) as response:
                    if response.status_code != 200:
                        raise KnownError("HTTP "+str(response.status_code))
                    body=response.json()
                    nested=body.get("data") or {}
                    token=body.get("token") or body.get("access_token") or nested.get("token") or nested.get("access_token")
                    if not isinstance(token,str) or not token:
                        raise KnownError("missing token")
                result["login_ok"]=True
                event("ok")
                step="connect"
                started=time.perf_counter()
                ws=websocket.create_connection(cfg["WS_URL"],header={"Authorization":"Bearer "+token},timeout=15)
                result["connection_ok"]=True
                connected=True
                with lock:
                    active+=1
                    peak=max(peak,active)
                event("ok")
                step="synchronize"
                started=time.perf_counter()
                ready[device["device_id"]].set()
                if not go.wait(timeout=90):
                    raise KnownError("start coordination timeout")
                for round_number in range(args.rounds):
                    step="device_request"
                    started=time.perf_counter()
                    device["payload"]["client_data"]["ref"] += 1
                    ws.send(json.dumps(device["payload"]))
                    result["requests_sent"]+=1
                    deadline=time.monotonic()+15
                    while True:
                        remaining=deadline-time.monotonic()
                        if remaining<=0:
                            raise KnownError("matching response timeout")
                        ws.settimeout(remaining)
                        raw=ws.recv()
                        if not raw:
                            raise KnownError("connection closed")
                        try:
                            reply=json.loads(raw)
                        except (json.JSONDecodeError,UnicodeDecodeError):
                            result["background_messages"]+=1
                            continue
                        if not isinstance(reply,dict) or reply.get("udid")!=device["payload"]["udid"] or reply.get("client_data",{}).get("ref")!=device["payload"]["client_data"]["ref"] or reply.get("messagetype")!=1:
                            result["background_messages"]+=1
                            continue
                        outcome=classify(reply,device["payload"])
                        break
                    result["replies_received"]+=1
                    if outcome == "acknowledged":
                        result["acknowledged_requests"]+=1
                    result["outcomes"].append(outcome)
                    if len(result["response_samples"])<2:
                        result["response_samples"].append(sanitized(reply))
                    event(outcome)
                    # Never continue after rejection or a reply that cannot be matched.
                    if outcome != "acknowledged":
                        break
                    if round_number+1<args.rounds:
                        time.sleep(5)
        except Exception as exc:
            error=str(exc) if isinstance(exc,KnownError) else type(exc).__name__
            if isinstance(exc,websocket.WebSocketBadStatusException):
                error="websocket HTTP "+str(exc.status_code)
            result["outcomes"].append(error)
            event(error)

        finally:
            ready[device["device_id"]].set()
            if connected:
                with lock:
                    active-=1
            if ws:
                try:
                    ws.close(timeout=1)
                except Exception:
                    pass
        return result
    with ThreadPoolExecutor(max_workers=len(devices)) as pool:
        jobs=[]
        for index,device in enumerate(devices):
            jobs.append(pool.submit(worker,device))
            if index+1<len(devices):
                time.sleep(1/args.spawn_rate)
        for signal in ready.values():
            signal.wait()
        print(f"Startup complete: {active}/{len(devices)} connected; starting dummy requests.",flush=True)
        go.set()
        results=[job.result() for job in jobs]
    groups={}
    for platform in ("ios","android"):
        subset=[r for r in results if r["platform"]==platform]
        times=[e["duration_ms"] for e in events if e["platform"]==platform and e["step"]=="device_request"]
        groups[platform]=dict(dummy_devices=len(subset),login_ok=sum(r["login_ok"] for r in subset),
                              connections=sum(r["connection_ok"] for r in subset),
                              requests_sent=sum(r["requests_sent"] for r in subset),
                              replies_received=sum(r["replies_received"] for r in subset),
                              acknowledged_requests=sum(r["acknowledged_requests"] for r in subset),
                              devices_with_acknowledgment=sum(r["acknowledged_requests"]>0 for r in subset),
                              explicitly_rejected=sum("rejected" in r["outcomes"] for r in subset),
                              unvalidated_replies=sum("unvalidated_response" in r["outcomes"] for r in subset),
                              background_messages=sum(r["background_messages"] for r in subset),
                              failed_devices=sum(any(o != "acknowledged" for o in r["outcomes"]) for r in subset),
                              diagnostics_completed=0,request_attempt_p95_ms=percentile(times,.95))
    summary=dict(scope="exploratory synthetic device payloads, shared account",
                 peak_connections=peak,spawn_rate=args.spawn_rate,requested_rounds=args.rounds,platforms=groups,devices=results,
                 limitations=["Android device_info schema is assumed, not verified.",
                              "Synthetic iOS fixture contains only a subset of real-device plist fields.",
                              "Acknowledgment requires status=success and matching udid, client_data.ref and messagetype; it does not prove diagnostic completion.",
                              "No hardware/USB or desktop UI behavior is exercised.",
                              "Only message type 1 is repeated; returned hardware commands are not executed. Unmatched/non-JSON messages are counted separately; each request waits up to 15 seconds for its matching reply."])
    (out/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    import csv
    with (out/"devices.csv").open("w",newline="",encoding="utf-8") as handle:
        fields=["platform","device_id","dummy_udid","login_ok","connection_ok","requests_sent","replies_received","acknowledged_requests","background_messages","diagnostics_completed","outcomes"]
        writer=csv.DictWriter(handle,fieldnames=fields,extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    (out/"events.json").write_text(json.dumps(events,indent=2),encoding="utf-8")
    lines=["# Dummy iOS and Android device test","",
           "This measures synthetic device-request acknowledgments, not completed hardware diagnostics.",
           f"Peak concurrent sockets: {peak}.", "",
           "| Platform | Dummy devices | Requests sent | Acknowledged requests | Explicit rejections | Verified diagnostics |",
           "|---|---:|---:|---:|---:|---:|"]
    for platform,g in groups.items():
        lines.append(f"| {platform} | {g['dummy_devices']} | {g['requests_sent']} | {g['acknowledged_requests']} | {g['explicitly_rejected']} | 0 |")
    lines+=["","## Per-device observations",""]
    lines += [f"- {r['device_id']}: {', '.join(r['outcomes']) or 'no outcome'}." for r in results]
    lines+=["","## Limits",""]+["- "+s for s in summary["limitations"]]
    (out/"experience_report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in summary.items() if k != "devices"},indent=2))
    print(f"Report: {out/'experience_report.md'}")
    return 1 if any(g["failed_devices"] for g in groups.values()) else 0


class KnownError(Exception):
    pass


if __name__=="__main__":
    raise SystemExit(main())

