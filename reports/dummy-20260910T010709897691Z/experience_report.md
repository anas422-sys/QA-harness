# Dummy iOS and Android device test

This measures synthetic device-request acknowledgments, not completed hardware diagnostics.
Peak concurrent sockets: 20.

| Platform | Dummy devices | Requests sent | Acknowledged requests | Explicit rejections | Verified diagnostics |
|---|---:|---:|---:|---:|---:|
| ios | 10 | 59 | 49 | 0 | 0 |
| android | 10 | 60 | 50 | 0 | 0 |

## Per-device observations

- ios-01: acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.
- android-01: acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.
- ios-02: acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.
- android-02: acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.
- ios-03: acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.
- android-03: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.
- ios-04: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.
- android-04: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.
- ios-05: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.
- android-05: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.
- ios-06: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.
- android-06: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.
- ios-07: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.
- android-07: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.
- ios-08: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.
- android-08: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, JSONDecodeError.
- ios-09: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.
- android-09: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.
- ios-10: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.
- android-10: acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, acknowledged, mismatched_response.

## Limits

- Android device_info schema is assumed, not verified.
- Synthetic iOS fixture contains only a subset of real-device plist fields.
- Acknowledgment requires status=success and matching udid, client_data.ref and messagetype; it does not prove diagnostic completion.
- No hardware/USB or desktop UI behavior is exercised.
- Only message type 1 is repeated; returned hardware commands are not executed. Each device stops on a rejected or unmatched response.
