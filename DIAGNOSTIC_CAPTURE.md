# Capturing a complete reCheck360 diagnostic

The Python tool capture_diagnostic_flow.py reads the application's own log without modifying the installation or executing device commands.

## Existing-log analysis completed
The extracted report is [capture_report.md](reports/protocol-20260910T122646790904/capture_report.md).
It contains 149 logged WebSocket messages and one pseudonymous device.
The type-8 validation exchange took 9,988 ms between the logged send and reply. This is a single historical observation, not a percentile or measured screen wait.
The log includes device information, app-install requests, battery results, OEM results and validation results. A full diagnostic completion/save event has not been verified.

The bundled USB tool detected zero iPhones at inspection time. A fresh end-to-end run requires reconnecting/unlocking the phone.

## Capture a fresh run
1. Connect the phone and confirm its card shows device details in reCheck360.
2. Start the capture below.
3. Run the application's normal diagnostic workflow. Perform any required physical interactions on the phone.
4. Wait for the final on-screen result and note its completion time. The capture tool itself does not click buttons or start tests.
5. Review capture_report.md, timeline.csv, protocol_schemas.json and desktop_metrics.json in the newly created reports/protocol-* folder.

```powershell
python capture_diagnostic_flow.py --watch-seconds 180
```

The watch mode needs psutil, already installed with Locust in this environment. It samples the reCheck360 processes once a second. CPU percent is relative to one logical core and can exceed 100% for a multithreaded process; RSS is resident process memory. The first CPU sample is blank while measurement initializes. Missing process samples can indicate process exit or insufficient access. This is not a UI-freeze or crash detector.

Without --watch-seconds the tool analyzes the latest existing log:
```powershell
python capture_diagnostic_flow.py
```

Specify another log with --log if needed. Watch mode follows the selected file and stops with an error if it detects truncation; for a run crossing daily log rollover, capture/analyze the new file separately. Full journey boundaries and a final diagnostic completion marker still need confirmation.

## Protocol mapping and simulator work remaining
The exported schemas intentionally contain field names, types and string lengths rather than actual tokens, phone identifiers, command strings or hardware outputs. References and devices receive local pseudonyms.

Requests and replies are matched by message type and request reference; device labels must agree when both are present. Missing captured replies are not automatically marked application failures. Late replies, partial logs and notifications must be investigated.

The current dummy simulator tests only message type 1. Before expanding it:
- Create synthetic result fixtures for the captured battery/OEM/validation command sequence.
- Validate these fixtures against staging and verify field-level results, not only status=success.
- Obtain a real Android capture; the current Android fixture is exploratory.
- Confirm the final diagnostic/result-save contract against the dashboard and backend.
- Keep real-device execution separate from synthetic server requests. Never execute a server-provided command automatically from the simulator.

The current captured data does not justify reporting complete diagnostics for either the 20 dummy sessions or the real phone.

