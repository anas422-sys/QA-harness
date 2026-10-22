Login/connect failures are included. Each original fixture is assigned to one session.
Request success means status=success with matching UDID, message type and reference.
Percentiles cover successful device-request replies, not login, failures, screen times or hardware diagnostics.
Requests.csv includes failed operation durations. Diagnostic CSV contains only observed type-15 snapshots; no fresh completion is inferred.
Original device_info is preserved. Inspect embedded_udid_matches: mismatches prevent claiming realistic distinct-device coverage.
All sessions share one account. Failed sessions stop rather than silently reconnecting.
Background messages are filtered; the response timeout applies to the whole wait, not each unrelated message.
