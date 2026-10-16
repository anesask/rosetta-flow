| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 | 0.66 | 0.48 | 0.65 | 0.63 | 0.32 | 0.47 | 0.54 / 0.64 | 0.66 | 5 | 4.10 | 27.20 | 14409 |
| audit70B | 0.68 | 0.60 | 0.74 | 0.88 | 0.52 | 0.72 | 0.51 / 0.67 | 0.89 | 2 | 3.80 | 22.10 | 12579 |
| B1 screens, audit70B confirms | 0.73 | 0.60 | 0.71 | 0.65 | 0.18 | 0.55 | 0.58 / 0.73 | 0.92 | 0 | 5.90 | 39.90 | 20213 |

Recall by error type (found and pointed at the right step):

| Error type | B1 | audit70B | B1 screens, audit70B confirms |
|---|---|---|---|
| contradicts_tool_result | 0.43 | 0.86 | 0.43 |
| false_completion | 0.50 | 0.75 | 0.62 |
| hallucinated_fact | 0.12 | 0.62 | 0.38 |
| ignored_tool_error | 0.57 | 0.86 | 0.57 |
| language_mismatch | 0.67 | 0.33 | 0.33 |
| skipped_required_step | 1.00 | 1.00 | 1.00 |
| voucher_over_limit | 0.50 | 0.67 | 0.67 |
| wrong_order | 0.33 | 0.83 | 0.67 |
| wrong_tool_args | 0.17 | 0.50 | 0.33 |

Two tiers: 61 of 120 traces (51%) reach the confirmer, which then spends 46% of the tokens it would need alone.
