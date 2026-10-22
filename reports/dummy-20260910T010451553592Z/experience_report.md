# Dummy iOS and Android device test

This is exploratory dummy-device traffic, not validated diagnostic load.
Peak concurrent sockets: 2.

| Platform | Dummy devices | Requests sent | Replies | Explicit rejections | Verified diagnostics |
|---|---:|---:|---:|---:|---:|
| ios | 1 | 1 | 1 | 0 | 0 |
| android | 1 | 1 | 1 | 0 | 0 |

## Per-device observations

- ios-01: unvalidated_response.
- android-01: unvalidated_response.

## Limits

- Android device_info schema is assumed, not verified.
- Synthetic iOS fixture contains only a subset of real-device plist fields.
- First reply is not proof of processing or diagnostic completion; correlation contract is unknown.
- No hardware/USB or desktop UI behavior is exercised.
- Run stops each device after its first unvalidated/rejected reply.
