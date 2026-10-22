# user-01 / 15 iOS profile replay

{
  "response_timeout_seconds": 40.0,
  "users": 1,
  "user": "user-01",
  "ios_devices": 15,
  "planned_requests": 137,
  "sent": 137,
  "received": 132,
  "outcomes": {
    "ACK_ONLY": 111,
    "TIMEOUT": 11,
    "BATTERY_MATCH": 15
  },
  "command_drift_requests": 43,
  "session_error": ""
}

One login, one WebSocket. Two session requests, then nine message types for each of 15 devices. Each step sends its device requests before receiving their replies.
BATTERY_MATCH checks battery serial, design capacity, current capacity, health and cycles against the changed profile. Other success responses are ACK_ONLY, not full data validation.
New UDIDs may have no saved information for type 139. Application errors are preserved, not counted as success.
Recorded outputs are replayed even if current server command IDs differ; command_drift lists these differences. No hardware commands are executed.
The supplied current capacity 3720 exceeds design capacity 2030; health 80 does not reconcile with that ratio. These are intentionally unusual test values, not realistic measurements.
Source OEM warnings, empty command outputs and SIM-lock errors remain in the fixtures. A success envelope does not prove these checks worked.
See requests.csv for paired full JSON, errors, command-list differences and timings; messages_readable.log contains all captured messages. Authentication fields are redacted.