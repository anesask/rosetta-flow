| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 8B single prompt | 0.52 | 0.20 | 0.66 | 0.92 | 0.89 | 0.29 | 0.42 / 0.47 | 0.21 | 4 | 0.00 | 4.10 | 2408 |
| v2 8B | 0.52 | 0.27 | 0.52 | 0.53 | 0.50 | 0.27 | 0.17 / 0.44 | 0.79 | 1 | 3.50 | 11.00 | 10819 |
| 70B | 0.71 | 0.52 | 0.71 | 0.70 | 0.27 | 0.52 | 0.35 / 0.56 | 0.83 | 0 | 3.60 | 13.70 | 12399 |
| v2 8B screens, 70B confirms | 0.64 | 0.45 | 0.54 | 0.42 | 0.14 | 0.35 | 0.39 / 0.65 | 0.86 | 0 | 5.60 | 18.80 | 18179 |

Recall by error type (found and pointed at the right step):

| Error type | B0 8B single prompt | v2 8B | 70B | v2 8B screens, 70B confirms |
|---|---|---|---|---|
| contradicts_tool_result | 0.20 | 0.00 | 0.20 | 0.20 |
| data_leak | 0.33 | 0.17 | 0.50 | 0.33 |
| false_completion | 0.17 | 0.00 | 0.33 | 0.00 |
| hallucinated_fact | 0.00 | 0.17 | 0.83 | 0.67 |
| ignored_tool_error | 0.17 | 0.33 | 0.67 | 0.50 |
| language_mismatch | 0.00 | 0.20 | 0.60 | 0.40 |
| release_without_approval | 0.60 | 0.80 | 0.80 | 0.80 |
| scope_too_small | 0.00 | 0.00 | 0.20 | 0.20 |
| skipped_required_step | 0.20 | 0.40 | 0.60 | 0.40 |
| too_few_first_pieces | 1.00 | 0.00 | 0.00 | 0.00 |
| wrong_order | 0.20 | 0.60 | 0.60 | 0.60 |
| wrong_revision | 0.00 | 0.00 | 1.00 | 0.00 |
| wrong_tool_args | 1.00 | 0.67 | 0.33 | 0.17 |

Two tiers: 69 of 132 traces (52%) reach the confirmer, which then spends 59% of the tokens it would need alone.
