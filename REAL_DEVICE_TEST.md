# Test login, phone connection and diagnostics with 20 actual devices

The existing Locust script sends backend requests. Twenty Locust users do not launch the app on twenty phones or reproduce USB connections. For this test, collect actual device observations and automate the UI only after identifying whether the application is mobile, web, or Windows desktop.

## First run
1. Prepare 20 actual devices/emulators that support the diagnostic features being tested. Hardware/USB diagnostics may require physical phones. Assign one valid test account and device to each tester.
2. Record app version, device model, OS, network and test-server environment. Use consistent diagnostic scenarios and synchronized clocks.
3. Complete one baseline journey: login, connect phone, start diagnostics, wait for its final result. Note expected outcomes.
4. Start all 20 testers at an agreed time. Have everyone log in, connect their assigned phone, then wait until all are ready before starting diagnostics together. Record failures even if a user cannot reach the diagnostic step.
5. Measure each step from the user's action until visible success or failure. Record waiting, errors, crashes, freezes, recovery and screenshot/log evidence. Do not mark a diagnostic passed merely because the start request succeeded.
6. Capture application/server CPU, memory, database and error logs during the same interval to investigate reported difficulties. Repeat the same run to check reproducibility.

## Python reporting
No extra Python packages are required.

Create a blank 20-device CSV:
```powershell
python device_experience_report.py --init
```

Fill device_observations.csv in Excel or a text editor:
- user_id: keep the 20 unique generated labels.
- device_id: unique test asset label; avoid personal identifiers.
- *_status: pass, fail, blocked, or not_run. Blank means unrecorded.
- *_seconds: measured duration in seconds; leave blank if not measured.
- started_at / finished_at: overall journey timestamps including timezone, for example 2026-09-10T14:00:00+05:00.
- crashed / froze: yes or no, or blank if not observed.
- difficulty: actual visible problem or tester feedback; explicitly enter "none observed" when appropriate.
- recovery: what resolved the issue and how long it took.
- evidence: screenshot, screen recording or log reference. Do not include passwords or tokens.

Generate the report:
```powershell
python device_experience_report.py
```

The reports/<timestamp>/ folder contains experience_report.md and summary.json. Results include per-device outcomes, completed journeys, step p95 times, crashes/freezes and recorded difficulties. Overall journey overlap is only a coordination indicator; it is not proof of concurrent diagnostics. With 20 samples, percentile estimates are coarse.

## UI automation still needs app details
Supply the application type and launch/build location, connection mechanism (USB, Bluetooth, network), device inventory and exact screens/actions. Then use the appropriate UI driver to execute the same journey across 20 sessions and populate these observations automatically. Mobile automation requires app-specific selectors and device/server setup; it cannot be inferred from the WebSocket payload.

Until those are available, this is an executable reporting workflow for a coordinated manual device test, not an automated 20-device load runner. No real-device test results have been collected yet.

