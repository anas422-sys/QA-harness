# Daily QA Agents

## Enterprise harness

`start_harness.cmd` starts the local enterprise control panel at `http://127.0.0.1:8765`.
The screen has three clear top-level tabs:

- **Frontend:** Real USB Devices and Desktop Application Pages.
- **Backend:** API/WebSocket Messages and Dummy Device Load.
- **Logs & Results:** Test Results, Sent Messages and Received Messages, with separate downloads.

Those tabs expose four independent test modes:

1. **Sent / Received Messages** replays selected captured requests and produces separate sent and
   received tables and CSV files. PASS requires exact message type/reference correlation, successful
   status, and matching UDID when supplied.
2. **Dummy Devices** creates up to 20 synthetic iOS/Android identities. Its successful result is
   `ACKNOWLEDGED`, never a physical diagnostic PASS.
3. **Real USB Devices** lists up to 20 devices detected by the bundled Android/iOS tools. Its base
   result is `CONNECTED`; optional payload checks run only when the payload UDID matches a connected
   physical device.
4. **Desktop Pages** keeps desktop JavaFX page automation separate from device and message testing.

Every run writes `results.csv`, `messages_sent.csv`, `messages_received.csv`, `results.json`, and an
HTML report with timings and exact blockers.

The frontend catalogue is generated from the installed `app.jar`: 65 packaged JavaFX views and
2,127 declared controls/actions are currently indexed. Together with device-specific workflows,
the harness exposes 71 selectable frontend entries and eight backend feature suites.

Before the first full desktop run, keep the reCheck360 dashboard visible and use **Discover visible
app controls**. The control inventory is saved under `daily_qa/reports/calibration_*` and is used to
finish exact locators in `desktop_map.json`. Android requires `adb.exe`; iOS requires
`idevice_id.exe` and optionally `ideviceinfo.exe`. Their full paths can be set in `config.json`.
This workstation is configured to use the copies bundled with reCheck360.

Install desktop automation dependencies once:

```powershell
daily_qa\install_enterprise_requirements.cmd
```

This setup contains three roles:

1. Frontend QA Agent checks whether the reCheck360 desktop process is running and creates the daily manual UI checklist.
2. Backend QA Agent tests staging authentication, the WebSocket connection and a correlated version-message response. It also creates the backend manual checklist.
3. Daily Report Agent writes `results.csv`, `results.json` and a visible `dashboard.html` for every run.

## Visual test harness

Start the local control panel:

```powershell
daily_qa\start_harness.cmd
```

The harness opens at `http://127.0.0.1:8765`. It can run all agents, display live status,
show every automated result and let a tester save Pass, Fail, Blocked or Pending Manual
with evidence notes. It listens only on localhost.

Run now:

```powershell
python daily_qa\daily_qa.py
```

The output path is printed and saved to `daily_qa\latest_report.txt`. Open
`daily_qa\latest_dashboard.html` at any time to view the newest results.

Install the 09:00 daily Windows schedule:

```powershell
powershell -ExecutionPolicy Bypass -File daily_qa\install_daily_schedule.ps1
```

Manual checks remain `PENDING MANUAL` until a tester performs them. They are never counted as automated passes. Credentials are read from the existing `locustfile.py` and are not written to reports.
