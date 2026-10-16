| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B3-alone | 0.69 | 0.54 | 0.71 | 0.76 | 0.39 | 0.58 | 0.36 / 0.61 | 0.84 | 1 | 3.80 | 17.80 | 13264 |
| B1 | 0.59 | 0.26 | 0.58 | 0.56 | 0.39 | 0.26 | 0.31 / 0.62 | 0.47 | 8 | 4.50 | 33.30 | 18305 |
| verify70B | 0.35 | 0.24 | 0.43 | 0.50 | 0.81 | 0.27 | 0.35 / 0.59 | 0.56 | 62 | 0.00 | 3.60 | 2694 |
| B1 screens, verify70B confirms | 0.65 | 0.32 | 0.59 | 0.50 | 0.19 | 0.27 | 0.35 / 0.59 | 0.56 | 0 | 4.50 | 35.00 | 19652 |

Recall by error type (found and pointed at the right step):

| Error type | B3-alone | B1 | verify70B | B1 screens, verify70B confirms |
|---|---|---|---|---|
| contradicts_tool_result | 0.20 | 0.20 | 0.20 | 0.20 |
| data_leak | 0.83 | 0.17 | 0.33 | 0.33 |
| false_completion | 0.83 | 0.33 | 0.50 | 0.50 |
| hallucinated_fact | 0.80 | 0.40 | 0.40 | 0.40 |
| ignored_tool_error | 1.00 | 0.20 | 0.20 | 0.20 |
| language_mismatch | 0.14 | 0.14 | 0.14 | 0.14 |
| release_without_approval | 1.00 | 1.00 | 1.00 | 1.00 |
| scope_too_small | 0.00 | 0.00 | 0.00 | 0.00 |
| skipped_required_step | 0.80 | 0.20 | 0.20 | 0.20 |
| too_few_first_pieces | 0.00 | 0.00 | 0.00 | 0.00 |
| wrong_order | 0.20 | 0.40 | 0.20 | 0.20 |
| wrong_revision | 0.00 | 0.00 | 0.00 | 0.00 |
| wrong_tool_args | 1.00 | 0.00 | 0.00 | 0.00 |

Two tiers: 62 of 124 traces (50%) reach the confirmer, which then spends 100% of the tokens it would need alone.
