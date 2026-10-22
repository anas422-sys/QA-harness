2 sessions share ONE account. 20 synthetic identities; no physical device connections.
Stages: 20, 20, 20 device requests; 60 total planned. Startup reference exchanges run once per session.
messages.log contains actual sent/received WebSocket JSON, with credential/token fields redacted. HTTP authentication bodies are not logged. Uncorrelated received messages remain in the log.
ACK_ONLY means correlated success, not verified hardware results or equivalent device-info structure. Android fixtures are exploratory.
Reference compares schemas and stable-value hashes. VALUE_CHANGED requires configuration review. Missing reference messages, logout and session creation are excluded.
Latency percentiles in platform_summary.csv cover acknowledgments only; inspect failures separately. Sessions are client sockets, not proof of simultaneous server processing.
No returned commands, USB diagnostics, erasure or updates are executed. No desktop CPU/UI experience is measured. This bounded load test does not determine maximum server capacity.
