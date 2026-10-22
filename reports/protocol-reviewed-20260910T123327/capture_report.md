# Diagnostic protocol capture

Scope: historical log through latest available device activity; not the idle three-minute recording. Source: app-2026-09-10.log.
Messages: 163. Device identities observed: 1.
Unpaired received messages: 6; unparseable messages skipped: 0.

## Recorded request/reply steps

| Type | Observed step | Requests | Matched replies | Max logged reply time ms |
|---|---|---:|---:|---:|
| 1 | Device information | 2 | 2 | 726.0 |
| 2 | Unmapped application message | 2 | 2 | 511.0 |
| 3 | Battery command request (inferred) | 2 | 2 | 480.0 |
| 4 | Battery results | 2 | 2 | 798.0 |
| 5 | OEM command request (inferred) | 2 | 2 | 706.0 |
| 6 | OEM results | 2 | 2 | 509.0 |
| 7 | Validation command request (inferred) | 2 | 2 | 500.0 |
| 8 | Validation results | 2 | 2 | 9988.0 |
| 12 | App-install command request | 2 | 2 | 554.0 |
| 29 | Unmapped application message | 2 | 2 | 1029.0 |
| 30 | Unmapped application message | 2 | 2 | 762.0 |
| 32 | Unmapped application message | 6 | 6 | 1142.0 |
| 33 | Unmapped application message | 2 | 2 | 676.0 |
| 34 | Unmapped application message | 4 | 3 | 665.0 |
| 39 | Unmapped application message | 2 | 1 | 441.0 |
| 45 | Unmapped application message | 2 | 2 | 930.0 |
| 49 | Unmapped application message | 2 | 2 | 677.0 |
| 53 | Unmapped application message | 2 | 2 | 924.0 |
| 54 | Unmapped application message | 2 | 1 | 666.0 |
| 56 | Unmapped application message | 2 | 2 | 690.0 |
| 58 | Unmapped application message | 2 | 2 | 675.0 |
| 59 | Unmapped application message | 2 | 2 | 682.0 |
| 60 | Unmapped application message | 2 | 2 | 677.0 |
| 62 | Unmapped application message | 2 | 2 | 679.0 |
| 64 | Unmapped application message | 2 | 1 | 866.0 |
| 67 | Unmapped application message | 2 | 2 | 677.0 |
| 70 | Unmapped application message | 2 | 1 | 761.0 |
| 72 | Unmapped application message | 0 | 0 | None |
| 101 | Unmapped application message | 2 | 2 | 923.0 |
| 103 | Unmapped application message | 2 | 2 | 669.0 |
| 119 | Unmapped application message | 1 | 1 | 358.0 |
| 120 | Unmapped application message | 2 | 2 | 895.0 |
| 127 | Unmapped application message | 2 | 2 | 680.0 |
| 134 | Unmapped application message | 2 | 2 | 470.0 |
| 135 | Unmapped application message | 2 | 2 | 676.0 |
| 138 | 3uTools integration data | 2 | 2 | 606.0 |
| 139 | Unmapped application message | 2 | 2 | 746.0 |
| 140 | OEM2 data | 2 | 2 | 521.0 |
| 141 | Unmapped application message | 4 | 0 | None |

## What this establishes

The timeline matches logged outgoing requests to incoming replies by message type and request reference, checking device identity when both sides include it.
Device identifiers and references are replaced by local labels. Schemas retain field names, types and string lengths, not credentials or hardware data.
Timestamps are local application log times. Differences measure logged request/reply intervals, not total hardware execution or UI response.
No reply in this capture does not prove a timeout; the reply may fall outside the captured log or logging coverage.
An acknowledged payload is not proof that a full diagnostic passed. Final diagnostic completion has not been verified.

## Next protocol work

Build synthetic command-result fixtures for each observed step; do not replay this phone's data.
Validate Android's separate command/result schemas using a real Android capture.
Identify the explicit final diagnostic completion/result-save event and verify that the dashboard agrees.
Compiled message-name constants are not treated as authoritative: the log uses message numbers differently in some cases.
Only then extend the simulator to a complete journey. Do not execute commands from captured or server-returned payloads automatically.
