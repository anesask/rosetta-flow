| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B2v2 8B (fixes) | 0.62 | 0.47 | 0.66 | 0.74 | 0.49 | 0.52 | 0.38 / 0.68 | 0.72 | 0 | 3.50 | 10.70 | 9385 |
| 70B | 0.69 | 0.60 | 0.73 | 0.85 | 0.48 | 0.69 | 0.51 / 0.71 | 0.85 | 0 | 3.60 | 15.70 | 11316 |
| B2v2 8B (fixes) screens, 70B confirms | 0.67 | 0.53 | 0.66 | 0.63 | 0.29 | 0.51 | 0.55 / 0.79 | 0.89 | 0 | 5.80 | 21.30 | 17078 |

Recall by error type (found and pointed at the right step):

| Error type | B2v2 8B (fixes) | 70B | B2v2 8B (fixes) screens, 70B confirms |
|---|---|---|---|
| contradicts_tool_result | 0.29 | 0.86 | 0.43 |
| false_completion | 0.50 | 0.75 | 0.62 |
| hallucinated_fact | 0.00 | 0.33 | 0.00 |
| ignored_tool_error | 0.86 | 1.00 | 1.00 |
| language_mismatch | 0.20 | 0.60 | 0.40 |
| skipped_required_step | 1.00 | 1.00 | 1.00 |
| voucher_over_limit | 0.67 | 0.33 | 0.17 |
| wrong_order | 0.83 | 1.00 | 0.83 |
| wrong_tool_args | 0.83 | 0.50 | 0.33 |

Two tiers: 80 of 130 traces (62%) reach the confirmer, which then spends 68% of the tokens it would need alone.
