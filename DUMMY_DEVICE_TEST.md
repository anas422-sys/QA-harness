# Dummy-device load test results

## Final measured run
Date: 2026-09-10. Target: configured staging server. One shared account, 20 distinct synthetic device identities. Two sessions started per second. Each session sent 12 message-type-1 device requests, waiting five seconds between responses and the next request.

| Platform | Dummy identities attempted | Connected | Requests sent | Matched success acknowledgments | Failed devices | Request p95 |
|---|---:|---:|---:|---:|---:|---:|
| iOS | 10 | 10 | 120 | 120 | 0 | 918.77 ms |
| Android | 10 | 10 | 120 | 120 | 0 | 774.65 ms |

Peak simultaneous connections: 20. Background/unmatched messages observed: 15 on iOS sessions, 13 on Android sessions. These were handled separately from request replies. p95 is based on 120 device-request attempts per platform and excludes login/connection times; it is not screen-loading time.

A request counts as acknowledged only when the response has status=success and matches the synthetic udid, client_data.ref and messagetype. This validates the message-type-1 acknowledgment only.

Detailed final artifacts:
- [Platform and per-device report](reports/dummy-20260910T010942478564Z/experience_report.md)
- [Per-device CSV, including dummy UDIDs and platform](reports/dummy-20260910T010942478564Z/devices.csv)
- [Summary and redacted response samples](reports/dummy-20260910T010942478564Z/summary.json)
- [Per-request measurements](reports/dummy-20260910T010942478564Z/events.json)

## Difficulties encountered
1. An earlier 20-session simultaneous-login burst produced 7 HTTP 429 login responses and 4 WebSocket handshake failures. HTTP 429 indicates request throttling; the responsible component and rate-limit policy were not established. The harness then aborted its all-session start barrier, cancelling 9 connected sessions. No device payloads were sent in that burst. This is a startup finding, not a completed 20-device diagnostic stress test. [Burst report](reports/dummy-20260910T010558498570Z/experience_report.md)
2. The first gradual run stopped when background/unmatched messages arrived, with one JSON parsing error. The test initially assumed each next frame was the outstanding response. That assumption was corrected to filter unrelated frames and wait up to 15 seconds for a matched reply. Those earlier stops should not be presented as proven application defects. [Intermediate report](reports/dummy-20260910T010709897691Z/experience_report.md)
3. The Android fixture schema remains exploratory. Staging acknowledged it but returned limited parsed device details in the initial probe. The iOS fixture is a minimal synthetic plist, not a full physical-device dump.

## What a user may experience
The startup burst suggests some simultaneous sign-in attempts can be throttled or unable to establish a connection under this shared-account scenario. The final gradual run observed no such failures. The measured request latencies describe backend waiting only; no subjective feedback or desktop screen timing was collected.

## Scope limits
- Simulated device requests: 10 iOS and 10 Android. Physical devices tested by this script: zero.
- Completed hardware diagnostics: zero. Returned hardware commands are not executed.
- All sessions use the account already configured in locustfile.py. This is not a 20-independent-account test.
- Android ID shape is synthetic and the platform metadata is assigned by the fixture; it does not emulate the Android runtime.
- No USB behavior, desktop UI freezes, device hardware accuracy, or server resource utilization was measured.
- This is a short, bounded load test and a startup burst probe, not a capacity limit or breaking-point stress benchmark.

## Repeat
Run from this workspace:
```powershell
python run_dummy_devices.py --per-platform 10 --rounds 12 --spawn-rate 2
```
Each run generates fresh dummy identities and a new reports/dummy-<UTC timestamp>/ folder. Maximum supported target is 10 dummy identities per platform. Settings are read from locustfile.py without importing or executing its tasks. The runner uses the existing requests and websocket-client packages.

To inspect platform counts in Excel, open devices.csv and filter the platform column. Count distinct dummy_udid values; do not count repeated requests as extra devices.

Before expanding beyond message type 1, obtain the actual Android fixture format and complete diagnostic command/result protocol. Use valid synthetic fixtures and independent test accounts for representative diagnostic load.

