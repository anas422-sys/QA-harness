# Dummy iOS and Android device test

This measures synthetic device-request acknowledgments, not completed hardware diagnostics.
Peak concurrent sockets: 1.

| Platform | Dummy devices | Requests sent | Acknowledged requests | Explicit rejections | Verified diagnostics |
|---|---:|---:|---:|---:|---:|
| ios | 10 | 0 | 0 | 0 | 0 |
| android | 10 | 0 | 0 | 0 | 0 |

## Per-device observations

- ios-01: BrokenBarrierError.
- android-01: WebSocketBadStatusException.
- ios-02: BrokenBarrierError.
- android-02: BrokenBarrierError.
- ios-03: HTTP 429.
- android-03: HTTP 429.
- ios-04: HTTP 429.
- android-04: BrokenBarrierError.
- ios-05: BrokenBarrierError.
- android-05: HTTP 429.
- ios-06: HTTP 429.
- android-06: BrokenBarrierError.
- ios-07: BrokenBarrierError.
- android-07: HTTP 429.
- ios-08: BrokenBarrierError.
- android-08: WebSocketBadStatusException.
- ios-09: WebSocketBadStatusException.
- android-09: BrokenBarrierError.
- ios-10: HTTP 429.
- android-10: WebSocketBadStatusException.

## Limits

- Android device_info schema is assumed, not verified.
- Synthetic iOS fixture contains only a subset of real-device plist fields.
- Acknowledgment requires status=success and matching udid, client_data.ref and messagetype; it does not prove diagnostic completion.
- No hardware/USB or desktop UI behavior is exercised.
- Only message type 1 is repeated; returned hardware commands are not executed. Each device stops on a rejected or unmatched response.
