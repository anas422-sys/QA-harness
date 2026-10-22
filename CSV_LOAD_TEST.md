# CSV load test based on your pasted code

Keep `csv_load_test.py` and `csv_load_devices.json` together. The JSON contains the 14 payloads extracted from your attachment, without its password. All 14 outer device IDs are iOS; no Android payloads were supplied.

Install dependencies if needed:

```powershell
python -m pip install locust==2.46.4 websocket-client==1.9.2 websockets==17.1
```

Generate a local demonstration with synthetic data and no staging traffic:

```powershell
python csv_load_test.py --demo --duration 15
```

Run against your configured staging server:

```powershell
python csv_load_test.py --duration 60 --spawn-rate 2
```

The live mode gets the password from `RECHECK_PASSWORD`, or from an existing `locustfile.py` with the same username. If neither is available, an interactive terminal prompts for it without echoing. It does not import or execute the original locustfile. Do not put a password in the CSV or the JSON fixture file.

The requested live run has not been executed by the assistant: automatic approval review requires explicit approval to send the exact private device identities to staging. Local-demo timings are not application performance results.

## CSV output

Each invocation creates a unique directory under `reports/`:

| File | Contents |
|---|---|
| requests.csv | Every login, connection and device request; timing, bytes received, success/failure, session, platform and ID |
| devices.csv | Per-session request counts, failures, p50/p95 timing and identity-consistency flag |
| platform_summary.csv | iOS/Android counts and aggregated request results |
| diagnostic_results.csv | Only type-15 diagnostic snapshots actually received during request waits; otherwise headers only |
| run_summary.csv | Target/started users, peak connections, failures, acknowledgments, fixture issues and execution mode |

CSV files use UTF-8 with BOM for Excel. Every data row identifies `local_demo` or `staging`. Secrets and raw response bodies are not exported. Request rows flush as operations finish; final summaries are written on normal stop or Ctrl+C. A forcibly terminated process can leave only partial request rows.

## Behavior and limits

- Each session gets one of the supplied payloads. The default is 14 sessions, not 14 payloads repeated by every virtual user. `--users` can select fewer; additional users require additional unique payloads.
- Login, connection, HTTP 429 responses, receive timeouts and application-level failures are measured.
- Replies must match UDID, message type and a new request reference and have `status=success`. Unrelated messages do not count as successful replies.
- Original payload fields are preserved except `client_data.ref`, which is regenerated for correlation. The script retains 1–3 second think time. Duration includes ramp-up; graceful draining can extend wall-clock runtime.
- All 14 supplied `device_info` blobs contain the same embedded iPhone UDID, which differs from their outer UDIDs. The script flags this instead of modifying your data. These fixtures do not establish realistic coverage of 14 independent phones.
- Success means a device-request acknowledgment, not a completed diagnostic or a real USB-device test. Repeated acknowledgments are not extra devices.
- Result snapshots may contain saved results. `fresh_run_verified` stays false, and missing snapshots are not fabricated.
- All sessions use the shared account. Failed sessions stop, so inspect started sessions, peak connections and per-device outcomes rather than assuming the target load was sustained.

Implementation uses Locust's custom protocol request events: https://docs.locust.io/en/stable/testing-other-systems.html

Offline CSV checks:

```powershell
python test_csv_load_test.py
```
