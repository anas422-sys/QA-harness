# Concurrent session performance report

Transport check: PASS. Target: 20 sessions.
Peak sockets: 20; hold start/end: 20/20. Hold: 60s.
Failed operations: 0.

| Step | Attempts | Failures | Successful p50 ms | Successful p95 ms |
|---|---:|---:|---:|---:|
| login | 20 | 0 | 1186.24 | 1520.44 |
| connect | 20 | 0 | 1140.3 | 1419.41 |
| ping_pong | 253 | 0 | 357.16 | 462.36 |

## Difficulties

- No login, connection, or ping/pong failures observed.

## Meaning and limits

Login/setup times indicate potential waiting before connection; ping/pong measures network and WebSocket transport responsiveness.
These are simulated sessions sharing one account. Open sockets and pong replies do not establish that all sessions retain application authorization.
No diagnostic payloads were sent. No USB, hardware diagnostics, desktop UI response, or subjective user experience was measured.
This is an initial 20-session load probe, not a breaking-point stress test or proof of diagnostic capacity.
PASS means connections survived this interval with successful heartbeat checks; no product latency SLA was supplied.
Next: validate a diagnostic request/result contract, supply distinct test accounts/consistent synthetic fixtures, then run sustained diagnostic traffic.
