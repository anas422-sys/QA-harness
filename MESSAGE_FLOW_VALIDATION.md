# Validate the same message flow and returned data

`validate_message_flow.py` extracts matched outgoing requests and successful replies from a reference reCheck360 log, then performs those requests for simulated iOS and Android sessions on staging. It reuses `settings()` from `run_session_load.py` and `fixture()` from `run_dummy_devices.py`; keep those files alongside it.

```powershell
python validate_message_flow.py --reference-log "path\to\reference-log.txt" --per-platform 10 --spawn-rate 2
```

The September 22 attachment provides 25 request variants across 22 message types. Each session performs those startup/configuration requests once, sequentially, followed by one synthetic type-1 device-information request. All sessions share the existing test account. This reproduces observed request contents, but not the desktop's parallel request scheduling or hardware execution.

## CSV outcomes

- MATCH: required fields/types and stable response values agree with an observed reference variant.
- VALUE_CHANGED: structure matches but stable data changed; investigate configuration/account changes before calling it a defect.
- SCHEMA_MISMATCH: missing fields, incorrect types, or an empty list where the reference was nonempty.
- ISOLATION_MISMATCH: the correlated reply identifies a different account/device.
- APPLICATION_FAILURE: a correlated response did not have status=success.
- ERROR: login, connection, transport, parsing or timeout error.
- NOT_RUN: the session became unavailable before that step.
- ACK_ONLY_NO_REFERENCE: type-1 transport/application acknowledgment was received, but this attachment provides no type-1 response contract.

Replies are correlated by message type and request reference. Device IDs are checked when the request contains one; startup requests generally have no device ID. Unrelated messages are counted separately. Response waits have an overall timeout.

Required structure allows extra fields. Array order is ignored for value comparisons. Response value fingerprints exclude token fields, timestamps, username, UDID and client_data; username and applicable UDIDs are validated separately. CSV differences do not export raw account details or response tokens. `reference_contract.json` contains request templates, response schemas and stable-value hashes, not raw response values.

## Artifacts

- validation.csv: each session/step, outcome, timing, mismatch detail and unrelated message count.
- message_summary.csv: counts/outcomes and maximum response time by platform/message type.
- reference_gaps.csv: excluded requests and missing matched reference responses; missing log data is not treated as a server failure.
- reference_contract.json: the extracted validation contract.
- README.txt: scope and interpretation.

The default 2,000 ms slow flag is provisional, not an agreed product SLA. A nonzero exit indicates errors or differences to review, including VALUE_CHANGED.

## Coverage boundaries

Logout (18) and session creation (134) are excluded to avoid altering shared session state. Unmatched references, including type 103 in the attachment, are not invented. Returned software-update URLs, commands, erase flags and other settings are read as response data, never executed.

The supplied attachment does not provide the full device-specific command/results protocol, a diagnostic-start event, or a final completion assertion. Android device fixtures remain exploratory. No successful run of this script proves USB behavior, real sensor accuracy, a fresh complete diagnostic, or desktop responsiveness.
