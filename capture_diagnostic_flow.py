"""Extract redacted request/reply timelines from reCheck360 logs; never replay hardware commands."""
import argparse
from collections import Counter, defaultdict, deque
from datetime import datetime
import csv
import json
from pathlib import Path
import time

LABELS = {1:"Device information",3:"Battery command request (inferred)",
          4:"Battery results",5:"OEM command request (inferred)",6:"OEM results",
          7:"Validation command request (inferred)",8:"Validation results",
          12:"App-install command request",138:"3uTools integration data",140:"OEM2 data"}
DEVICE_TYPES = set(LABELS)


def shape(value, key=""):
    """Keep field names and types, never account/device/command/result values."""
    if isinstance(value,dict):
        return {k:shape(v,k) for k,v in value.items()}
    if isinstance(value,list):
        return {"type":"array","items":shape(value[0]) if value else None,"count":len(value)}
    if key in ("messagetype","cmd_id") and isinstance(value,int):
        return value
    if isinstance(value,str):
        return {"type":"string","length":len(value)}
    return {"type":type(value).__name__}


def parse(lines):
    records=[]
    aliases={}
    references={}
    skipped=0
    for number,line in enumerate(lines,1):
        if "WebSocketManager" not in line:
            continue
        direction="sent" if "Message sent:" in line else "received" if "Received message:" in line else None
        if not direction or "{" not in line:
            continue
        try:
            timestamp=datetime.strptime(line[:23],"%Y-%m-%d %H:%M:%S.%f")
            obj=json.JSONDecoder().raw_decode(line[line.index("{"):])[0]
            if not isinstance(obj,dict):
                raise ValueError()
        except (ValueError,TypeError):
            skipped+=1
            continue
        kind=obj.get("messagetype")
        if not isinstance(kind,int):
            skipped+=1
            continue
        client=obj.get("client_data")
        ref=client.get("ref") if isinstance(client,dict) else None
        if ref is not None:
            raw_ref=json.dumps(ref,sort_keys=True)
            reference=references.setdefault(raw_ref,f"request-{len(references)+1:03d}")
        else:
            reference=None
        identity=obj.get("udid")
        reply=obj.get("reply")
        if not identity and isinstance(reply,dict):
            identity=reply.get("udid")
        alias=aliases.setdefault(str(identity),f"device-{len(aliases)+1:02d}") if identity else None
        status=obj.get("status")
        safe_status=status if isinstance(status,str) and status.lower() in ("success","error","failed","failure","pending","ok") else "other" if status is not None else None
        records.append(dict(line=number,time=timestamp.isoformat(timespec="milliseconds"),
                            direction=direction,message_type=kind,device=alias,
                            request=reference,status=safe_status,schema=shape(obj)))
    return records,skipped


def analyze(records):
    pending=defaultdict(deque)
    exchanges=[]
    notifications=0
    for event in records:
        key=(event["message_type"],event["request"])
        if event["direction"]=="sent":
            if event["request"] is not None:
                pending[key].append(event)
            else:
                exchanges.append(dict(message_type=event["message_type"],device=event["device"],
                                      request=None,sent_at=event["time"],reply_at=None,
                                      duration_ms=None,outcome="uncorrelatable_send"))
        elif event["request"] is not None and pending[key]:
            request=pending[key][0]
            if request["device"] and event["device"] and request["device"]!=event["device"]:
                notifications+=1
                continue
            pending[key].popleft()
            elapsed=(datetime.fromisoformat(event["time"])-datetime.fromisoformat(request["time"])).total_seconds()*1000
            outcome="acknowledged" if event["status"] in ("success","ok") else "reply_"+str(event["status"])
            exchanges.append(dict(message_type=event["message_type"],
                                  device=request["device"] or event["device"],
                                  request=event["request"],sent_at=request["time"],reply_at=event["time"],
                                  duration_ms=round(elapsed,2),outcome=outcome))
        else:
            notifications+=1
    for queue in pending.values():
        for event in queue:
            exchanges.append(dict(message_type=event["message_type"],device=event["device"],
                                  request=event["request"],sent_at=event["time"],reply_at=None,
                                  duration_ms=None,outcome="no_reply_in_capture"))
    exchanges.sort(key=lambda e:e["sent_at"])
    return exchanges,notifications


def write_report(records, skipped, output, source, metrics=None, scope="existing log"):
    output.mkdir(parents=True,exist_ok=False)
    exchanges,notifications=analyze(records)
    groups=[]
    for kind in sorted({r["message_type"] for r in records}):
        items=[e for e in exchanges if e["message_type"]==kind]
        times=[e["duration_ms"] for e in items if e["duration_ms"] is not None]
        groups.append(dict(message_type=kind,label=LABELS.get(kind,"Unmapped application message"),
                           outgoing=len(items),matched=sum(e["reply_at"] is not None for e in items),
                           outcomes=dict(Counter(e["outcome"] for e in items)),
                           max_reply_ms=max(times) if times else None))
    summary=dict(source_filename=source.name,scope=scope,recorded_messages=len(records),
                 skipped_unparseable_messages=skipped,
                 pseudonymous_devices=len({r["device"] for r in records if r["device"]}),
                 unpaired_received_messages=notifications,steps=groups,
                 complete_diagnostic_journey_verified=False)
    (output/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    (output/"protocol_schemas.json").write_text(json.dumps(records,indent=2),encoding="utf-8")
    with (output/"timeline.csv").open("w",newline="",encoding="utf-8") as handle:
        fields=["message_type","device","request","sent_at","reply_at","duration_ms","outcome"]
        writer=csv.DictWriter(handle,fieldnames=fields)
        writer.writeheader()
        writer.writerows(exchanges)
    if metrics is not None:
        (output/"desktop_metrics.json").write_text(json.dumps(metrics,indent=2),encoding="utf-8")
    lines=["# Diagnostic protocol capture","",
           f"Scope: {scope}. Source: {source.name}.",
           f"Messages: {len(records)}. Device identities observed: {summary['pseudonymous_devices']}.",
           f"Unpaired received messages: {notifications}; unparseable messages skipped: {skipped}.",
           "", "## Recorded request/reply steps", "",
           "| Type | Observed step | Requests | Matched replies | Max logged reply time ms |",
           "|---|---|---:|---:|---:|"]
    for g in groups:
        lines.append(f"| {g['message_type']} | {g['label']} | {g['outgoing']} | {g['matched']} | {g['max_reply_ms']} |")
    lines+=["","## What this establishes","",
            "The timeline matches logged outgoing requests to incoming replies by message type and request reference, checking device identity when both sides include it.",
            "Device identifiers and references are replaced by local labels. Schemas retain field names, types and string lengths, not credentials or hardware data.",
            "Timestamps are local application log times. Differences measure logged request/reply intervals, not total hardware execution or UI response.",
            "No reply in this capture does not prove a timeout; the reply may fall outside the captured log or logging coverage.",
            "An acknowledged payload is not proof that a full diagnostic passed. Final diagnostic completion has not been verified.",
            "", "## Next protocol work","",
            "Build synthetic command-result fixtures for each observed step; do not replay this phone's data.",
            "Validate Android's separate command/result schemas using a real Android capture.",
            "Identify the explicit final diagnostic completion/result-save event and verify that the dashboard agrees.",
            "Compiled message-name constants are not treated as authoritative: the log uses message numbers differently in some cases.",
            "Only then extend the simulator to a complete journey. Do not execute commands from captured or server-returned payloads automatically."]
    (output/"capture_report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return summary


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--log",type=Path)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--watch-seconds",type=int,default=0,help="Capture newly appended log lines and desktop resource samples.")
    args=parser.parse_args()
    if args.watch_seconds<0:
        parser.error("watch-seconds must be nonnegative")
    files=list((Path.home()/".recheck360"/"logs").glob("app-*.log"))
    source=args.log or (max(files,key=lambda p:p.stat().st_mtime) if files else None)
    if source is None:
        parser.error("No application log found; provide --log.")
    metrics=None
    scope="existing log, historical observations"
    if args.watch_seconds:
        import psutil
        scope=f"new log lines during {args.watch_seconds}-second capture; no automatic UI actions"
        offset=source.stat().st_size
        metrics=[]
        tracked={}
        deadline=time.monotonic()+args.watch_seconds
        print("Capturing new log activity and reCheck360 resource use.",flush=True)
        while time.monotonic()<deadline:
            sample=dict(time=datetime.now().isoformat(timespec="seconds"),processes=[])
            for proc in psutil.process_iter(["pid","name"]):
                if (proc.info["name"] or "").lower() != "recheck360.exe":
                    continue
                try:
                    key=(proc.pid,proc.create_time())
                    old=tracked.get(key)
                    if old is None:
                        tracked[key]=proc
                        proc.cpu_percent()
                        cpu=None
                    else:
                        proc=old
                        cpu=proc.cpu_percent()
                    sample["processes"].append(dict(pid=proc.pid,cpu_percent_one_core=cpu,
                                                   rss_mb=round(proc.memory_info().rss/1024**2,2),
                                                   threads=proc.num_threads()))
                except (psutil.NoSuchProcess,psutil.AccessDenied):
                    continue
            metrics.append(sample)
            time.sleep(min(1,max(0,deadline-time.monotonic())))
        if source.stat().st_size<offset:
            raise RuntimeError("Log rotated or truncated; capture again against the current log.")
        with source.open("rb") as handle:
            handle.seek(offset)
            lines=handle.read().decode("utf-8",errors="replace").splitlines()
    else:
        lines=source.read_text(encoding="utf-8",errors="replace").splitlines()
    records,skipped=parse(lines)
    output=args.output or Path(__file__).resolve().parent/"reports"/datetime.now().strftime("protocol-%Y%m%dT%H%M%S%f")
    summary=write_report(records,skipped,output,source,metrics,scope)
    print(json.dumps(summary,indent=2))
    print(f"Report: {output/'capture_report.md'}")


if __name__=="__main__":
    main()

