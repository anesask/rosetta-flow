| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 8B single prompt | 0.50 | 0.20 | 0.66 | 0.98 | 0.98 | 0.29 | 0.26 / 0.37 | 0.25 | 1 | 0.00 | 3.50 | 2018 |
| B1 8B | 0.62 | 0.41 | 0.63 | 0.63 | 0.39 | 0.41 | 0.52 / 0.59 | 0.64 | 5 | 3.20 | 18.70 | 9792 |
| 70B | 0.69 | 0.60 | 0.73 | 0.85 | 0.48 | 0.69 | 0.51 / 0.71 | 0.85 | 0 | 3.60 | 15.70 | 11316 |
| B1 8B screens, 70B confirms | 0.69 | 0.56 | 0.67 | 0.63 | 0.25 | 0.52 | 0.56 / 0.79 | 0.86 | 0 | 5.20 | 28.40 | 16292 |

Recall by error type (found and pointed at the right step):

| Error type | B0 8B single prompt | B1 8B | 70B | B1 8B screens, 70B confirms |
|---|---|---|---|---|
| contradicts_tool_result | 0.29 | 0.43 | 0.86 | 0.43 |
| false_completion | 0.25 | 0.50 | 0.75 | 0.62 |
| hallucinated_fact | 0.11 | 0.00 | 0.33 | 0.00 |
| ignored_tool_error | 0.57 | 0.57 | 1.00 | 0.86 |
| language_mismatch | 0.30 | 0.40 | 0.60 | 0.30 |
| skipped_required_step | 0.50 | 0.67 | 1.00 | 1.00 |
| voucher_over_limit | 0.00 | 0.67 | 0.33 | 0.33 |
| wrong_order | 0.17 | 0.33 | 1.00 | 1.00 |
| wrong_tool_args | 0.50 | 0.33 | 0.50 | 0.50 |

Two tiers: 70 of 130 traces (54%) reach the confirmer, which then spends 57% of the tokens it would need alone.
