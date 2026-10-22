"""Report real diagnostic result snapshots and compare them with the logged test plan."""
import argparse
from collections import Counter
import csv
from datetime import datetime
import json
from pathlib import Path

PASS = {"pass", "passed"}
FAIL = {"fail", "failed"}
NOT_APPLICABLE = {"not applicable", "n/a", "not_applicable"}
SKIPPED = {"skipped", "skip"}


def evaluate(tests, plan=None, excluded=()):
    codes=[t.get("code") for t in tests]
    duplicates=[code for code,count in Counter(codes).items() if count>1]
    actual={t.get("code"):t for t in tests if isinstance(t.get("code"),str) and t["code"]}
    required={t["code"]:t for t in plan or [] if t.get("is_enabled") is True and isinstance(t.get("code"),str)}
    exclusions=set(excluded)
    expected=set(required)-exclusions
    missing=sorted(expected-set(actual))
    rows=[]
    for test in tests:
        raw=str(test.get("result","")).strip()
        status=raw.lower()
        category=("pass" if status in PASS else "fail" if status in FAIL else
                  "not_applicable" if status in NOT_APPLICABLE else
                  "skipped" if status in SKIPPED else "unresolved")
        rows.append(dict(code=test.get("code"),test_name=test.get("test_name"),
                         result=raw,category=category,enabled=test.get("is_enabled"),
                         hidden=test.get("is_hidden")))
    counts=dict(Counter(row["category"] for row in rows))
    unresolved=[row["code"] for row in rows if row["category"] in ("unresolved","skipped") and row["code"] in expected]
    known_plan=plan is not None and bool(expected)
    invalid_codes=any(not isinstance(c,str) or not c for c in codes)
    coverage=known_plan and not missing and not duplicates and not invalid_codes and not unresolved
    return dict(result_count=len(rows),expected_enabled_count=len(required) if plan is not None else None,
                required_after_exclusions=len(expected) if plan is not None else None,
                counts=counts,missing_tests=[dict(code=c,test_name=required[c].get("test_name")) for c in missing],
                excluded_codes=sorted(exclusions),duplicate_codes=duplicates,
                unresolved_required_codes=unresolved,
                reported_required_results_complete=bool(coverage),
                all_required_reported_pass=bool(coverage and all(
                    str(actual[c].get("result","")).lower().strip() in PASS for c in expected)),
                fresh_diagnostic_run_verified=False,tests=rows)


def extract(lines, excluded=()):
    plans={}
    devices={}
    platforms={}
    snapshots=[]
    for line in lines:
        if "WebSocketManager" not in line or "{" not in line:
            continue
        try:
            obj=json.JSONDecoder().raw_decode(line[line.index("{"):])[0]
        except ValueError:
            continue
        if not isinstance(obj,dict):
            continue
        identity=obj.get("udid")
        if identity:
            device=devices.setdefault(str(identity),f"device-{len(devices)+1:02d}")
            platform=obj.get("device_operating_system")
            if platform in ("ios","android"):
                platforms[device]=platform
        else:
            device=None
        if "Received message:" not in line:
            continue
        reply=obj.get("reply")
        if not isinstance(reply,dict):
            continue
        kind=obj.get("messagetype")
        if kind==32 and isinstance(reply.get("tests"),list):
            plans[reply.get("name")]=reply["tests"]
        if kind!=15 or not isinstance(reply.get("tests"),list):
            continue
        # Do not treat an unassociated payload as a verified device result.
        snapshot=dict(timestamp=line[:23],device=device or "unassociated",
                      platform=platforms.get(device,"unknown"),message_type=15,
                      success_envelope=obj.get("status")=="success",
                      **evaluate(reply["tests"],plans.get(reply.get("name")),excluded))
        if not snapshot["success_envelope"] or device is None:
            snapshot["reported_required_results_complete"]=False
            snapshot["all_required_reported_pass"]=False
        snapshots.append(snapshot)
    return snapshots


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--log",type=Path)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--exclude-code",action="append",default=[],
                        help="Explicitly exclude a code only after confirming device applicability.")
    args=parser.parse_args()
    files=list((Path.home()/".recheck360/logs").glob("app-*.log"))
    source=args.log or (max(files,key=lambda p:p.stat().st_mtime) if files else None)
    if source is None:
        parser.error("No log found; provide --log")
    snapshots=extract(source.read_text(encoding="utf-8",errors="replace").splitlines(),args.exclude_code)
    latest={}
    for snapshot in snapshots:
        latest[snapshot["device"]]=snapshot
    out=args.output or Path(__file__).resolve().parent/"reports"/datetime.now().strftime("diagnostic-results-%Y%m%dT%H%M%S%f")
    out.mkdir(parents=True,exist_ok=False)
    summary=dict(source=source.name,snapshot_events=len(snapshots),
                 devices_with_result_snapshots=len(latest),devices=list(latest.values()),
                 all_snapshots=snapshots,scope="stored/reported diagnostic results, not proof of a fresh test run")
    (out/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    with (out/"test_results.csv").open("w",newline="",encoding="utf-8") as handle:
        fields=["device","platform","snapshot_time","code","test_name","result","category","enabled","hidden"]
        writer=csv.DictWriter(handle,fieldnames=fields)
        writer.writeheader()
        for device in latest.values():
            for test in device["tests"]:
                writer.writerow(dict(device=device["device"],platform=device["platform"],
                                     snapshot_time=device["timestamp"],**test))
    lines=["# Individual diagnostic results","",
           f"Result snapshot events: {len(snapshots)}. Devices with snapshots: {len(latest)}.",
           "These are server-reported results from message type 15. Fresh-run completion and hardware accuracy are not independently established.",
           "", "| Device | Platform | Reported tests | Pass | Fail | Enabled in matching plan | Missing required |",
           "|---|---|---:|---:|---:|---:|---:|"]
    for device in latest.values():
        counts=device["counts"]
        lines.append(f"| {device['device']} | {device['platform']} | {device['result_count']} | {counts.get('pass',0)} | {counts.get('fail',0)} | {device['expected_enabled_count']} | {len(device['missing_tests'])} |")
    lines+=["","## Coverage findings",""]
    for device in latest.values():
        lines.append(f"- {device['device']}: all required results accounted for = {device['reported_required_results_complete']}.")
        for missing in device["missing_tests"]:
            lines.append(f"- No result for {missing['test_name']} ({missing['code']}). Confirm hardware applicability before calling this a failed or omitted test.")
    if not latest:
        lines.append("- No result snapshot found. No completed diagnostic is claimed.")
    lines+=["","## Individual reported outcomes","",
            "| Device | Code | Test | Result |","|---|---|---|---|"]
    for device in latest.values():
        for test in device["tests"]:
            # Escape table separators in text without exposing other message content.
            values=[device["device"],test["code"],test["test_name"],test["result"]]
            lines.append("| "+" | ".join(str(v).replace("|","/").replace("\n"," ") for v in values)+" |")
    lines+=["","## Completion contract for future load tests","",
            "A status=success acknowledgment is insufficient. Observe the correct device's type-15 result snapshot and compare the required test codes with an applicable test plan.",
            "Match the snapshot to the current diagnostic cycle using an authoritative cycle ID or documented fresh-result rule. Type 15 in this capture has no request reference.",
            "A new receive timestamp is not proof the tests ran recently; saved results may be pushed when a device reconnects.",
            "Treat pass/fail as terminal reported outcomes, keep skipped/pending/missing results separate, and require explicit applicability for excluded tests.",
            "Record elapsed time from a verified diagnostic start to its matching final result event; this capture does not establish that start/end pair.",
            "Android requires its own observed result contract and applicable test plan. Do not fabricate passing results or replay this phone's identity.",
            "The current dummy-device runner remains a message-type-1 load test."]
    (out/"results_report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in summary.items() if k not in ("devices","all_snapshots")},indent=2))
    for device in latest.values():
        print(json.dumps({k:v for k,v in device.items() if k!="tests"},indent=2))
    print(f"Report: {out/'results_report.md'}")


if __name__=="__main__":
    main()

