# Dummy iOS and Android device test

This measures synthetic device-request acknowledgments, not completed hardware diagnostics.
Peak concurrent sockets: 20.

| Platform | Dummy devices | Requests sent | Acknowledged requests | Explicit rejections | Verified diagnostics |
|---|---:|---:|---:|---:|---:|
| ios | 10 | 114 | 113 | 0 | 0 |
| android | 10 | 120 | 120 | 0 | 0 |

## Per-device observations

- ios-01: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.
- android-01: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.
- ios-02: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.
- android-02: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.
- ios-03: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.
- android-03: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.
- ios-04: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.
- android-04: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.
- ios-05: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.
- android-05: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.
- ios-06: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.
- android-06: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.
- ios-07: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.
- android-07: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.
- ios-08: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, WebSocketTimeoutException.
- android-08: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.
- ios-09: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.
- android-09: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.
- ios-10: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.
- android-10: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged.

## Limits

- Android device_info schema is assumed, not verified.
- Synthetic iOS fixture contains only a subset of real-device plist fields.
- Acknowledgment requires status=success and matching udid, client_data.ref and messagetype; it does not prove diagnostic completion.
- No hardware/USB or desktop UI behavior is exercised.
- Only message type 1 is repeated; returned hardware commands are not executed. Unmatched/non-JSON messages are counted separately; each request waits up to 15 seconds for its matching reply.
