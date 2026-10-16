| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 8B (fixes) | 0.65 | 0.44 | 0.67 | 0.69 | 0.39 | 0.46 | 0.50 / 0.57 | 0.67 | 5 | 3.80 | 19.50 | 11242 |
| 70B | 0.69 | 0.60 | 0.73 | 0.85 | 0.48 | 0.69 | 0.51 / 0.71 | 0.85 | 0 | 3.60 | 15.70 | 11316 |
| B1 8B (fixes) screens, 70B confirms | 0.71 | 0.59 | 0.69 | 0.65 | 0.21 | 0.55 | 0.53 / 0.78 | 0.86 | 0 | 5.90 | 30.00 | 18041 |

Recall by error type (found and pointed at the right step):

| Error type | B1 8B (fixes) | 70B | B1 8B (fixes) screens, 70B confirms |
|---|---|---|---|
| contradicts_tool_result | 0.57 | 0.86 | 0.71 |
| false_completion | 0.38 | 0.75 | 0.38 |
| hallucinated_fact | 0.11 | 0.33 | 0.11 |
| ignored_tool_error | 0.71 | 1.00 | 0.86 |
| language_mismatch | 0.50 | 0.60 | 0.50 |
| skipped_required_step | 1.00 | 1.00 | 1.00 |
| voucher_over_limit | 0.50 | 0.33 | 0.33 |
| wrong_order | 0.33 | 1.00 | 1.00 |
| wrong_tool_args | 0.17 | 0.50 | 0.33 |

Two tiers: 74 of 130 traces (57%) reach the confirmer, which then spends 60% of the tokens it would need alone.
