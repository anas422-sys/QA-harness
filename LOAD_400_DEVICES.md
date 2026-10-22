# Run the 20-session / 400-device staging test

From this folder in PowerShell:

```powershell
python run_400_devices.py
```

The script reads the existing staging login settings from `locustfile.py`. Keep `run_session_load.py`, `run_dummy_devices.py`, and `validate_message_flow.py` alongside it. It uses the installed `requests` and `websocket-client` packages. The local `.venv` currently lacks these dependencies; use the working system `python` shown above.

There are 20 sessions sharing one account, with 10 simulated iOS and 10 simulated Android devices assigned to each. Each session opens one WebSocket. The 20 devices share that session's connection. Device references and identities are unique; replies are matched by reference/message type and checked for account and device identity.

The supplied reference log is reread on every run. Its 25 startup request variants run once per session. Device stages then send 5, 10, 20, 20 and 20 requests per session, totaling 1,500 planned device requests. All participating sessions finish a stage before the next starts. Sessions start at two per second. This is a bounded stepped load run, not a search for maximum server capacity.

Every run creates a new timestamped directory under `reports`:

- `messages.log`: timestamped actual WebSocket `Message sent:` and `Received message:` JSON. Authentication fields are redacted. Uncorrelated and late incoming messages are retained. Non-JSON content is recorded by length only.
- `assigned_devices.csv`: all 400 identities and their session/platform assignments.
- `requests.csv`: individual request outcomes, latency, platform, device, reference and mismatch details. Authentication connection measurements are included without credentials.
- `platform_summary.csv`, `user_summary.csv`, `stage_summary.csv`: aggregated outcomes and acknowledgment timings.
- `reference_gaps.csv`: missing reference responses and excluded logout/session-creation actions.
- `manifest.json`: test configuration and outcomes.

`ACK_ONLY` verifies a correlated success envelope. It does not verify returned hardware details against a real phone, execute returned commands, or prove that a diagnostic finished. The attached log lacks a device type-1 reference; the Android fixture is exploratory. `MATCH` refers to startup reference comparisons. `VALUE_CHANGED` can reflect account/configuration changes. Timeouts and unavailable sessions are failures/unexecuted work, never successes. Exit code 1 indicates findings requiring review, including reference differences.

Raw logs can contain the staging account's business data and should remain in your test workspace. The harness does not collect desktop CPU, memory, UI freezes, USB performance, or actual human observations.

Preparation without network calls:

```powershell
python run_400_devices.py --prepare-only
```

To use another reference log, pass `--reference-log "C:\path\to\pasted-text.txt"`.
