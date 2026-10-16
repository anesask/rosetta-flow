| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B3-alone | 0.68 | 0.60 | 0.74 | 0.88 | 0.52 | 0.72 | 0.51 / 0.67 | 0.89 | 2 | 3.80 | 22.10 | 12579 |
| B1 | 0.66 | 0.48 | 0.65 | 0.63 | 0.32 | 0.47 | 0.54 / 0.64 | 0.66 | 5 | 4.10 | 27.20 | 14409 |
| verify70B | 0.30 | 0.37 | 0.44 | 0.55 | 0.95 | 0.47 | 0.46 / 0.57 | 0.73 | 63 | 0.00 | 3.90 | 2360 |
| B1 screens, verify70B confirms | 0.64 | 0.51 | 0.61 | 0.55 | 0.27 | 0.47 | 0.46 / 0.57 | 0.73 | 4 | 4.10 | 29.20 | 15609 |

Recall by error type (found and pointed at the right step):

| Error type | B3-alone | B1 | verify70B | B1 screens, verify70B confirms |
|---|---|---|---|---|
| contradicts_tool_result | 0.86 | 0.43 | 0.57 | 0.57 |
| false_completion | 0.75 | 0.50 | 0.62 | 0.62 |
| hallucinated_fact | 0.62 | 0.12 | 0.25 | 0.25 |
| ignored_tool_error | 0.86 | 0.57 | 0.43 | 0.43 |
| language_mismatch | 0.33 | 0.67 | 0.67 | 0.67 |
| skipped_required_step | 1.00 | 1.00 | 0.67 | 0.67 |
| voucher_over_limit | 0.67 | 0.50 | 0.67 | 0.67 |
| wrong_order | 0.83 | 0.33 | 0.17 | 0.17 |
| wrong_tool_args | 0.50 | 0.17 | 0.17 | 0.17 |

Two tiers: 61 of 120 traces (51%) reach the confirmer, which then spends 100% of the tokens it would need alone.
