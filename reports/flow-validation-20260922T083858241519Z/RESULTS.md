# Staging message-flow validation

Target: 10 synthetic iOS sessions and 10 synthetic Android sessions; one shared account.
Reference: supplied September 22 log; 25 startup request variants across 22 message types.

| Outcome | Checks |
|---|---:|
| ACK_ONLY_NO_REFERENCE | 18 |
| APPLICATION_FAILURE | 54 |
| ERROR | 2 |
| MATCH | 202 |
| NOT_RUN | 44 |
| PASS | 39 |
| SCHEMA_MISMATCH | 91 |
| VALUE_CHANGED | 110 |

## Findings

- Startup/configuration data does not fully match the supplied reference.
- Test-plan requests (type 32) returned unsuccessful application responses. The result is not an account-isolation finding.
- Types 135, 49, 53, 54 and 45 included changes between arrays and null values; configuration differences need review.
- Value changes may reflect updated settings or account data. They are not automatically performance defects.
- Explicit errors and skipped steps are retained in validation.csv; skipped steps never count as matches.
- The device-information step has no reference response in this attachment and is acknowledgment-only.

## Files

- [Every validation](validation.csv)
- [Message summary](message_summary.csv)
- [Reference gaps](reference_gaps.csv)
- [Response schemas and value fingerprints](reference_contract.json)

This is not a complete diagnostic test. Hardware commands, USB behavior, device-specific final-result assertions and live screen timings remain outside this reference.
The earlier run in flow-validation-20260922T083537637920Z used an incorrect priority when classifying failed responses without usernames. Use this corrected run for conclusions.
