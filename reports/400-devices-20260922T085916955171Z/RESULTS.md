# Staging load test: 20 sessions, 400 simulated devices

Completed September 22, 2026. All 20 sessions logged in and opened WebSockets using **one shared account**. Each session was assigned 10 iOS and 10 Android synthetic identities. All 400 identities were attempted. These are simulated backend clients, not physical USB devices or 20 distinct accounts.

**Result: findings require investigation; this was not a clean pass.** Of 1,500 device requests, 1,456 received a correlated success acknowledgment (97.07%), 33 received application errors (2.20%), and 11 timed out after 15 seconds (0.73%). Across repeated rounds, 394 of 400 devices received at least one acknowledgment; six never did.

| Platform | Assigned / attempted | Devices acknowledged at least once | Successful requests | Application errors | Timeouts | p95 successful acknowledgment |
|---|---:|---:|---:|---:|---:|---:|
| iOS | 200 / 200 | 196 | 743 / 760 | 16 | 1 | 10.16 seconds |
| Android | 200 / 200 | 198 | 713 / 740 | 17 | 10 | 8.80 seconds |

The first stage uses five devices per session, alternating iOS/Android starting with iOS, so request totals differ slightly by platform even though assignments are 200 each. Percentiles above exclude failures and timeouts.

| Stage | Device requests | Acknowledged | Application errors | Timeouts | p95 acknowledgment |
|---|---:|---:|---:|---:|---:|
| 5 per session | 100 | 100 | 0 | 0 | 4.53 seconds |
| 10 per session | 200 | 198 | 0 | 2 | 4.80 seconds |
| 20 per session, round 1 | 400 | 387 | 11 | 2 | 10.23 seconds |
| 20 per session, round 2 | 400 | 390 | 10 | 0 | 9.98 seconds |
| 20 per session, round 3 | 400 | 381 | 12 | 7 | 8.79 seconds |

The server reported device-type update failures (10), license expiration or zero license count (5), transaction creation failures (10), and transaction fetch failures (8). These are observed server responses, not proven root causes. Backend logs and the shared account's licensing rules are needed to determine why they occurred. Repeated requests may affect transaction/license behavior; they do not reproduce a full physical disconnect/reconnect cycle.

Separately, the 500 startup reference checks produced 220 matches, 120 stable-value changes, 100 schema differences, and 60 application failures. All 60 startup application failures were message type 32, with `Test not found`. Configuration changes can explain reference differences; they are not automatically regressions. The supplied log has no matched type-1 device-information reference, so device successes remain acknowledgment-only.

The higher device stages showed longer waits and unsuccessful requests. A person might experience delayed or unsuccessful device registration, but no desktop UI or human experience was measured. No returned commands were executed and no hardware diagnostic completion was verified. This bounded stepped test does not establish maximum capacity or prove the desktop supports 400 USB devices.

Review `messages.log` for the actual sent/received JSON, `requests.csv` for individual measurements and server messages, `server_errors.csv` for grouped errors, and `device_results.csv` for each device's outcomes. Authentication fields are redacted in the log. `stage_summary.csv`, `platform_summary.csv` and `user_summary.csv` provide aggregates.

Before interpreting a follow-up run as hardware-equivalent, obtain the Android device-message schema and a complete diagnostic start/result contract. For investigating this run, first review licensing and transaction failures, then the missing test plans, and correlate the logged references with server-side timings.
