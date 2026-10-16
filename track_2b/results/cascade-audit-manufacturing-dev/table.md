| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 | 0.59 | 0.26 | 0.58 | 0.56 | 0.39 | 0.26 | 0.31 / 0.62 | 0.47 | 8 | 4.50 | 33.30 | 18305 |
| audit70B | 0.69 | 0.54 | 0.71 | 0.76 | 0.39 | 0.58 | 0.36 / 0.61 | 0.84 | 1 | 3.80 | 17.80 | 13264 |
| B1 screens, audit70B confirms | 0.69 | 0.46 | 0.62 | 0.50 | 0.11 | 0.37 | 0.35 / 0.70 | 0.82 | 1 | 6.50 | 44.20 | 25855 |

Recall by error type (found and pointed at the right step):

| Error type | B1 | audit70B | B1 screens, audit70B confirms |
|---|---|---|---|
| contradicts_tool_result | 0.20 | 0.20 | 0.20 |
| data_leak | 0.17 | 0.83 | 0.33 |
| false_completion | 0.33 | 0.83 | 0.50 |
| hallucinated_fact | 0.40 | 0.80 | 0.40 |
| ignored_tool_error | 0.20 | 1.00 | 0.60 |
| language_mismatch | 0.14 | 0.14 | 0.14 |
| release_without_approval | 1.00 | 1.00 | 1.00 |
| scope_too_small | 0.00 | 0.00 | 0.00 |
| skipped_required_step | 0.20 | 0.80 | 0.40 |
| too_few_first_pieces | 0.00 | 0.00 | 0.00 |
| wrong_order | 0.40 | 0.20 | 0.20 |
| wrong_revision | 0.00 | 0.00 | 0.00 |
| wrong_tool_args | 0.00 | 1.00 | 0.60 |

Two tiers: 62 of 124 traces (50%) reach the confirmer, which then spends 57% of the tokens it would need alone.
