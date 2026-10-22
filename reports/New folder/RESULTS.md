# Two sessions / 20 simulated devices

Same staging service; two sessions share one account. Each has five Android and five iOS devices.
Device labels identify simulated fixtures, not physical phones. No returned shell command was executed.

## Device message results

| Platform | Assigned | Acknowledged devices | Requests | Acknowledgments | p95 acknowledgment ms | Outcomes |
|---|---:|---:|---:|---:|---:|---|
| ios | 10 | 10 | 30 | 30 | 796.69 | {"ACK_ONLY": 30} |
| android | 10 | 10 | 30 | 28 | 750.12 | {"ACK_ONLY": 28, "TIMEOUT": 2} |

## Every device

| User | Device name | Platform | Model | OS | UDID | Acks | Failures |
|---|---|---|---|---|---|---:|---:|
| user-01 | user-01-iOS-01 | ios | iPhone 12 mini (simulated) | 18.0 | E341D6FB-1B125CCE8573CA2E | 3 | 0 |
| user-01 | user-01-Android-01 | android | Simulated Android | 14 | QAANDROID8B6A650D2676 | 3 | 0 |
| user-01 | user-01-iOS-02 | ios | iPhone 12 mini (simulated) | 18.0 | 923162D8-93E85615B5E72611 | 3 | 0 |
| user-01 | user-01-Android-02 | android | Simulated Android | 14 | QAANDROID1CBEDCC8F8F8 | 3 | 0 |
| user-01 | user-01-iOS-03 | ios | iPhone 12 mini (simulated) | 18.0 | 7A75C606-C71457CB92FC3632 | 3 | 0 |
| user-01 | user-01-Android-03 | android | Simulated Android | 14 | QAANDROIDD7B55691807E | 2 | 1 |
| user-01 | user-01-iOS-04 | ios | iPhone 12 mini (simulated) | 18.0 | 84BA1D71-79FE55A38E0210B6 | 3 | 0 |
| user-01 | user-01-Android-04 | android | Simulated Android | 14 | QAANDROID7ECDE7434006 | 2 | 1 |
| user-01 | user-01-iOS-05 | ios | iPhone 12 mini (simulated) | 18.0 | 34034A42-C48A5749A6DCEC76 | 3 | 0 |
| user-01 | user-01-Android-05 | android | Simulated Android | 14 | QAANDROIDF188B2283871 | 3 | 0 |
| user-02 | user-02-iOS-01 | ios | iPhone 12 mini (simulated) | 18.0 | BF0B1187-282D5B5C9FF285CC | 3 | 0 |
| user-02 | user-02-Android-01 | android | Simulated Android | 14 | QAANDROIDD0D956DE1E96 | 3 | 0 |
| user-02 | user-02-iOS-02 | ios | iPhone 12 mini (simulated) | 18.0 | A892D59F-75225C87955A8762 | 3 | 0 |
| user-02 | user-02-Android-02 | android | Simulated Android | 14 | QAANDROID215003EE8F9A | 3 | 0 |
| user-02 | user-02-iOS-03 | ios | iPhone 12 mini (simulated) | 18.0 | 5FB8D14B-B1B85E9CB9A7A2B8 | 3 | 0 |
| user-02 | user-02-Android-03 | android | Simulated Android | 14 | QAANDROIDC79D7402C55A | 3 | 0 |
| user-02 | user-02-iOS-04 | ios | iPhone 12 mini (simulated) | 18.0 | 1A91BED9-025857F189CA6B49 | 3 | 0 |
| user-02 | user-02-Android-04 | android | Simulated Android | 14 | QAANDROID955D2358F3D4 | 3 | 0 |
| user-02 | user-02-iOS-05 | ios | iPhone 12 mini (simulated) | 18.0 | C25B9730-F589512E8195ECDA | 3 | 0 |
| user-02 | user-02-Android-05 | android | Simulated Android | 14 | QAANDROID9509BD21498D | 3 | 0 |

## Server errors

- Type 32: Test not found (6 replies)

## Files and interpretation

- `messages_readable.log`: complete captured JSON in readable sent/received form; no ellipses or shortened payloads.
- `messages.log`: one timestamped JSON message per line in the reference log format, with device labels.
- `devices/`: separate readable log for every device that exchanged messages.
- `messages.csv`: every captured WebSocket message, including uncorrelated frames.
- `sent_received_pairs.csv`: full sent JSON and received JSON beside measured outcomes and response times.
- `assigned_devices.csv`: names, platforms, models, OS versions, UDIDs and decoded fixture information.
- `requests.csv`, `device_results.csv`, `user_summary.csv`, `platform_summary.csv`, `stage_summary.csv`: measurements and aggregates.

ACK_ONLY means a correlated success envelope, not verified hardware results. Android fixtures are exploratory. Model and OS columns describe submitted fixtures; full server-returned details are preserved in the message logs.
Startup checks compare 25 reference variants per session. Schema/value differences require review and are separate from device acknowledgment results. Authentication secrets are redacted; business data may remain in local logs.
No UI responsiveness, physical USB behavior, device diagnostic completion or human experience was measured. CSV percentiles cover successful acknowledgments only.

Overall measured outcomes: `{"PASS": 4, "VALUE_CHANGED": 12, "MATCH": 22, "SCHEMA_MISMATCH": 10, "APPLICATION_FAILURE": 6, "ACK_ONLY": 58, "TIMEOUT": 2}`.
