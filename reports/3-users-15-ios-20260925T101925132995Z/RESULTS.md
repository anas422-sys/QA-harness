# Three sessions, five iOS devices each

Three concurrent client sessions share the existing staging account. The first 15 existing generated device identities are reused; five unique identities are assigned to each session. No physical commands execute.
Each session performs 134 and 119 once, followed by device types 139,1,2,3,4,5,6,7,8. There are 141 planned requests total.
Raw recorded outputs are submitted even where current command lists differ; these differences are recorded and this is not a hardware-equivalent diagnostic run.
Battery values remain the supplied unusual values. BATTERY_MATCH checks the five returned fields against submitted values. Other successes are ACK_ONLY.
messages_readable.log is grouped by session, with timestamps on every entry. messages.csv can be sorted chronologically.

{
  "users": 3,
  "distinct_accounts": 1,
  "devices_per_user": 5,
  "ios_devices": 15,
  "planned_requests": 141,
  "sent": 141,
  "received": 140,
  "outcomes": {
    "ACK_ONLY": 124,
    "BATTERY_MATCH": 15,
    "TIMEOUT": 2
  },
  "command_drift_requests": 45,
  "sessions": [
    {
      "users": 1,
      "user": "user-01",
      "ios_devices": 5,
      "planned_requests": 47,
      "sent": 47,
      "received": 47,
      "outcomes": {
        "ACK_ONLY": 42,
        "BATTERY_MATCH": 5
      },
      "command_drift_requests": 15,
      "session_error": ""
    },
    {
      "users": 1,
      "user": "user-02",
      "ios_devices": 5,
      "planned_requests": 47,
      "sent": 47,
      "received": 46,
      "outcomes": {
        "ACK_ONLY": 40,
        "BATTERY_MATCH": 5,
        "TIMEOUT": 2
      },
      "command_drift_requests": 15,
      "session_error": ""
    },
    {
      "users": 1,
      "user": "user-03",
      "ios_devices": 5,
      "planned_requests": 47,
      "sent": 47,
      "received": 47,
      "outcomes": {
        "ACK_ONLY": 42,
        "BATTERY_MATCH": 5
      },
      "command_drift_requests": 15,
      "session_error": ""
    }
  ]
}