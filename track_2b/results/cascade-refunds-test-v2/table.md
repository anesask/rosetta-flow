| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 8B single prompt | 0.50 | 0.20 | 0.66 | 0.98 | 0.98 | 0.29 | 0.26 / 0.37 | 0.25 | 1 | 0.00 | 3.50 | 2018 |
| v2 8B | 0.64 | 0.46 | 0.69 | 0.79 | 0.51 | 0.52 | 0.35 / 0.68 | 0.78 | 0 | 3.40 | 11.20 | 9234 |
| 70B | 0.69 | 0.60 | 0.73 | 0.85 | 0.48 | 0.69 | 0.51 / 0.71 | 0.85 | 0 | 3.60 | 15.70 | 11316 |
| v2 8B screens, 70B confirms | 0.67 | 0.53 | 0.67 | 0.68 | 0.34 | 0.54 | 0.51 / 0.77 | 0.89 | 0 | 5.70 | 22.60 | 17196 |

Recall by error type (found and pointed at the right step):

| Error type | B0 8B single prompt | v2 8B | 70B | v2 8B screens, 70B confirms |
|---|---|---|---|---|
| contradicts_tool_result | 0.29 | 0.00 | 0.86 | 0.43 |
| false_completion | 0.25 | 0.50 | 0.75 | 0.50 |
| hallucinated_fact | 0.11 | 0.00 | 0.33 | 0.11 |
| ignored_tool_error | 0.57 | 0.86 | 1.00 | 1.00 |
| language_mismatch | 0.30 | 0.30 | 0.60 | 0.40 |
| skipped_required_step | 0.50 | 1.00 | 1.00 | 1.00 |
| voucher_over_limit | 0.00 | 0.67 | 0.33 | 0.33 |
| wrong_order | 0.17 | 1.00 | 1.00 | 1.00 |
| wrong_tool_args | 0.50 | 0.83 | 0.50 | 0.33 |

Two tiers: 84 of 130 traces (65%) reach the confirmer, which then spends 70% of the tokens it would need alone.
