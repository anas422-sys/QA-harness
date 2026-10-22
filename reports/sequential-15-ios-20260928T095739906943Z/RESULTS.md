# user-01 / 15 iOS profile replay

{
  "mode": "sequential baseline",
  "timeout_seconds": 60,
  "slow_threshold_seconds": 20,
  "users": 1,
  "user": "user-01",
  "ios_devices": 15,
  "planned_requests": 137,
  "sent": 107,
  "received": 108,
  "outcomes": {
    "ACK_ONLY": 77,
    "BLOCKED_MISSING_FIXTURE": 30,
    "BATTERY_MATCH": 15,
    "ACK_WITH_SOURCE_WARNINGS": 15
  },
  "command_drift_requests": 0,
  "session_error": ""
}

One login, one WebSocket. Two session requests, then nine message types for each of 15 devices. Requests are sequential, with a 60-second deadline. Responses exceeding 20 seconds are slow. No automatic retries.
BATTERY_MATCH checks battery serial, design capacity, current capacity, health and cycles against the changed profile. Other success responses are ACK_ONLY, not full data validation.
New UDIDs may have no saved information for type 139. Application errors are preserved, not counted as success.
Only the current requested command IDs/text are submitted. Missing fixtures block that step. These blocks remain incomplete, not passes. No hardware commands execute.
The supplied current capacity 3720 exceeds design capacity 2030; health 80 does not reconcile with that ratio. These are intentionally unusual test values, not realistic measurements.
Source OEM warnings, empty command outputs and SIM-lock errors remain in the fixtures. A success envelope does not prove these checks worked.
See requests.csv for paired full JSON, errors, command-list differences and timings; messages_readable.log contains all captured messages. Authentication fields are redacted.