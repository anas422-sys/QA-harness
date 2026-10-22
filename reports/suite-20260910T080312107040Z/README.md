# reCheck360 test suite

Run: all. Execution status: completed.

| Component | Execution | Detail |
|---|---|---|
| transport | completed |  |
| dummy | completed |  |
| diagnostic_results | completed |  |
| observations | completed |  |
| live_protocol | completed | Zero messages means no observed desktop protocol activity, not a successful diagnostic. |

## Dummy platform coverage

| Platform | Identities | Connected | Requests | Acknowledged | Failed devices | p95 ms |
|---|---:|---:|---:|---:|---:|---:|
| ios | 10 | 10 | 120 | 120 | 0 | 814.07 |
| android | 10 | 10 | 120 | 120 | 0 | 752.88 |

## Limits

- Dummy requests and transport checks use one shared test account and do not execute physical diagnostics.
- Individual result reports analyze saved snapshots; they cannot prove a new run completed.
- Desktop CPU/memory samples do not measure screen latency, freezes, or crash causes.
- Manual observations are included only when an existing CSV is supplied or available.
- Run all does not click desktop controls, start a physical diagnostic, erase phones, or alter device settings.

## Files

- [desktop_metrics.json](desktop_metrics.json)
- [diagnostic_results/results_report.md](diagnostic_results/results_report.md)
- [diagnostic_results/summary.json](diagnostic_results/summary.json)
- [diagnostic_results/test_results.csv](diagnostic_results/test_results.csv)
- [diagnostic_results_console.txt](diagnostic_results_console.txt)
- [dummy/devices.csv](dummy/devices.csv)
- [dummy/events.json](dummy/events.json)
- [dummy/experience_report.md](dummy/experience_report.md)
- [dummy/summary.json](dummy/summary.json)
- [dummy_console.txt](dummy_console.txt)
- [live_protocol/capture_report.md](live_protocol/capture_report.md)
- [live_protocol/protocol_schemas.json](live_protocol/protocol_schemas.json)
- [live_protocol/summary.json](live_protocol/summary.json)
- [live_protocol/timeline.csv](live_protocol/timeline.csv)
- [observations/experience_report.md](observations/experience_report.md)
- [observations/summary.json](observations/summary.json)
- [observations_console.txt](observations_console.txt)
- [suite_summary.json](suite_summary.json)
- [transport/events.csv](transport/events.csv)
- [transport/experience_report.md](transport/experience_report.md)
- [transport/summary.json](transport/summary.json)
- [transport/users.csv](transport/users.csv)
- [transport_console.txt](transport_console.txt)
