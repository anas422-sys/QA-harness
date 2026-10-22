"""Generate a report from observations on 20 real devices; no third-party packages."""
import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ["user_id", "device_id", "device_model", "os_version", "app_version", "network",
          "started_at", "finished_at", "login_status", "login_seconds",
          "connection_status", "connection_seconds", "diagnostic_status",
          "diagnostic_seconds", "crashed", "froze", "difficulty", "recovery", "evidence"]
STEPS = ("login", "connection", "diagnostic")


def p95(values):
    return sorted(values)[math.ceil(len(values)*.95)-1] if values else None


def timestamp(value):
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("Timestamps must include timezone, e.g. 2026-09-10T14:00:00+05:00")
    return result


def generate(source, output, target):
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not set(FIELDS).issubset(reader.fieldnames or []):
            raise ValueError("CSV is missing required columns; use --init.")
        rows = list(reader)
    if len(rows) != target:
        raise ValueError(f"Expected {target} device rows, found {len(rows)}.")
    users = [r["user_id"].strip() for r in rows]
    if len(set(users)) != target or not all(users):
        raise ValueError("Every row must have a unique user_id.")
    ids = [r["device_id"].strip() for r in rows if r["device_id"].strip()]
    if len(ids) != len(set(ids)):
        raise ValueError("device_id values must be unique.")
    intervals = []
    for index, row in enumerate(rows, 2):
        for step in STEPS:
            status = row[step+"_status"].strip().lower()
            row[step+"_status"] = status
            if status not in ("", "pass", "fail", "blocked", "not_run"):
                raise ValueError(f"Row {index}: invalid {step} status.")
            value = row[step+"_seconds"]
            if value:
                seconds = float(value)
                if not math.isfinite(seconds) or seconds < 0:
                    raise ValueError(f"Row {index}: duration must be finite and nonnegative.")
                row[step+"_seconds"] = seconds
            if status in ("pass", "fail", "blocked") and not row["device_id"].strip():
                raise ValueError(f"Row {index}: observed result requires device_id.")
        for key in ("crashed", "froze"):
            row[key] = row[key].strip().lower()
            if row[key] not in ("", "yes", "no"):
                raise ValueError(f"Row {index}: {key} must be yes, no, or blank.")
        if bool(row["started_at"]) != bool(row["finished_at"]):
            raise ValueError(f"Row {index}: provide both start and finish timestamps.")
        if row["started_at"]:
            start, end = timestamp(row["started_at"]), timestamp(row["finished_at"])
            if end <= start:
                raise ValueError(f"Row {index}: finish must be after start.")
            intervals.append((start, end))
    complete = sum(all(r[s+"_status"] == "pass" for s in STEPS) for r in rows)
    observed = sum(any(r[s+"_status"] in ("pass", "fail", "blocked") for s in STEPS) for r in rows)
    points = [(a, 1) for a, b in intervals] + [(b, -1) for a, b in intervals]
    active = peak = 0
    for _, change in sorted(points):
        active += change
        peak = max(peak, active)
    overlap = max(0, (min(b for a,b in intervals)-max(a for a,b in intervals)).total_seconds()) if len(intervals)==target else None
    stats = {}
    for step in STEPS:
        durations = [r[step+"_seconds"] for r in rows if r[step+"_seconds"] != ""]
        stats[step] = dict(statuses=dict(Counter(r[step+"_status"] or "unrecorded" for r in rows)),
                           timed_samples=len(durations), p95_seconds=p95(durations))
    summary = dict(target_devices=target, observed_devices=observed,
                   successful_journeys=complete, peak_overlapping_journeys=peak,
                   all_device_journey_overlap_seconds=overlap,
                   crashes=sum(r["crashed"]=="yes" for r in rows),
                   freezes=sum(r["froze"]=="yes" for r in rows), steps=stats,
                   devices=rows)
    lines = ["# Real-device experience report", "",
             f"Observed devices: {observed}/{target}. Successful full journeys: {complete}/{target}.",
             f"Reported crashes: {summary['crashes']}. Reported freezes: {summary['freezes']}.",
             f"Peak overlapping recorded journeys: {peak}.",
             f"Overlap across all {target} device journeys (seconds): {overlap if overlap is not None else 'not established'}.",
             "", "Times are tester observations. Overlapping journeys do not prove simultaneous backend requests or diagnostics.",
             "Blank fields mean unrecorded, never success. p95 includes all supplied durations, including failures.",
             "", "## Actions", ""]
    for step, data in stats.items():
        lines.append(f"- {step}: {data['statuses']}; timed samples {data['timed_samples']}; p95 {data['p95_seconds']} seconds.")
    lines += ["", "## User difficulties and recovery", ""]
    for r in rows:
        statuses = ", ".join(f"{s}={r[s+'_status'] or 'unrecorded'}" for s in STEPS)
        lines.append(f"- {r['user_id']}: {statuses}. Difficulty: {r['difficulty'] or 'unrecorded'}. Recovery: {r['recovery'] or 'unrecorded'}. Evidence: {r['evidence'] or 'unrecorded'}.")
    lines += ["", "## Interpretation", "",
              "Confirm defects using screenshots, screen recordings, application logs and matching server timestamps.",
              "No root cause, subjective feedback, or device behavior is inferred from missing evidence."]
    output.mkdir(parents=True, exist_ok=True)
    (output/"experience_report.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    (output/"summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true", help="Create a blank real-device observation CSV.")
    parser.add_argument("--csv", type=Path, default=Path("device_observations.csv"))
    parser.add_argument("--devices", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.devices < 1:
        parser.error("--devices must be positive")
    if args.init:
        with args.csv.open("x", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows({"user_id": f"user-{i:02d}"} for i in range(1,args.devices+1))
        print(f"Created {args.csv} with {args.devices} blank observations.")
    else:
        output = args.output or Path("reports") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        summary = generate(args.csv, output, args.devices)
        print(f"Report: {output / 'experience_report.md'}")
        print(f"Observed {summary['observed_devices']}/{args.devices} devices.")


if __name__ == "__main__":
    main()

