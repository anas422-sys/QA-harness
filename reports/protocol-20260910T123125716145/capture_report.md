# Diagnostic protocol capture

Scope: new log lines during 180-second capture; no automatic UI actions. Source: app-2026-09-10.log.
Messages: 0. Device identities observed: 0.
Unpaired received messages: 0; unparseable messages skipped: 0.

## Recorded request/reply steps

| Type | Observed step | Requests | Matched replies | Max logged reply time ms |
|---|---|---:|---:|---:|

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
