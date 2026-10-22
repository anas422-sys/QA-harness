# Capture status

The application log extractor and request/reply correlation checks are implemented in capture_diagnostic_flow.py. DIAGNOSTIC_CAPTURE.md explains use.

The actual iPhone was detected after reconnecting. Existing log data contains device information, battery, OEM, validation and installation exchanges. This establishes a partial real-device protocol sequence, not a verified completed diagnostic journey.

The separate 180-second recording at reports/protocol-20260910T123125716145 produced 172 desktop resource samples but zero new logged WebSocket messages. Every sample contained a reCheck360 process. The highest observed individual process RSS was 598.07 MiB, and the highest per-process CPU sample was 126.4 percent relative to one logical core. These measurements cover an interval without logged request traffic and must not be presented as diagnostic-load resource usage. The cause of that CPU sample has not been established.

Windows desktop captures continued to show VS Code over the target window. Automatic restores and direct window capture did not provide a reliable view of the diagnostic controls. No diagnostic UI action was clicked, and no server-issued hardware command was executed by the test tooling.

Next required evidence: a visible screenshot of the current reCheck360 dashboard to identify the actual diagnostic start control, followed by a fresh capture spanning start through final results. Physical phone interactions may still be required. Android full-flow coverage remains unavailable until an Android fixture/capture is supplied.
