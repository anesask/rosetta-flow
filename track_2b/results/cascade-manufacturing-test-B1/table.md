| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 8B single prompt | 0.52 | 0.20 | 0.66 | 0.92 | 0.89 | 0.29 | 0.42 / 0.47 | 0.21 | 4 | 0.00 | 4.10 | 2408 |
| B1 8B | 0.54 | 0.33 | 0.52 | 0.50 | 0.42 | 0.32 | 0.38 / 0.52 | 0.57 | 15 | 4.00 | 33.00 | 18040 |
| 70B | 0.71 | 0.52 | 0.71 | 0.70 | 0.27 | 0.52 | 0.35 / 0.56 | 0.83 | 0 | 3.60 | 13.70 | 12399 |
| B1 8B screens, 70B confirms | 0.67 | 0.46 | 0.57 | 0.44 | 0.09 | 0.35 | 0.26 / 0.56 | 0.80 | 0 | 6.00 | 40.60 | 24931 |

Recall by error type (found and pointed at the right step):

| Error type | B0 8B single prompt | B1 8B | 70B | B1 8B screens, 70B confirms |
|---|---|---|---|---|
| contradicts_tool_result | 0.20 | 0.20 | 0.20 | 0.00 |
| data_leak | 0.33 | 0.50 | 0.50 | 0.50 |
| false_completion | 0.17 | 0.17 | 0.33 | 0.17 |
| hallucinated_fact | 0.00 | 0.33 | 0.83 | 0.50 |
| ignored_tool_error | 0.17 | 0.50 | 0.67 | 0.50 |
| language_mismatch | 0.00 | 0.00 | 0.60 | 0.40 |
| release_without_approval | 0.60 | 0.80 | 0.80 | 0.80 |
| scope_too_small | 0.00 | 0.00 | 0.20 | 0.00 |
| skipped_required_step | 0.20 | 0.20 | 0.60 | 0.60 |
| too_few_first_pieces | 1.00 | 0.00 | 0.00 | 0.00 |
| wrong_order | 0.20 | 0.40 | 0.60 | 0.60 |
| wrong_revision | 0.00 | 0.33 | 1.00 | 0.33 |
| wrong_tool_args | 1.00 | 0.50 | 0.33 | 0.00 |

Two tiers: 69 of 132 traces (52%) reach the confirmer, which then spends 56% of the tokens it would need alone.
