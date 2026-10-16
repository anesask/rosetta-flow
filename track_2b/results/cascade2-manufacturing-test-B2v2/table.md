| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B2v2 8B (fixes) | 0.42 | 0.23 | 0.41 | 0.41 | 0.56 | 0.23 | 0.20 / 0.53 | 0.77 | 1 | 3.60 | 12.20 | 11103 |
| 70B | 0.71 | 0.52 | 0.71 | 0.70 | 0.27 | 0.52 | 0.35 / 0.56 | 0.83 | 0 | 3.60 | 13.70 | 12399 |
| B2v2 8B (fixes) screens, 70B confirms | 0.56 | 0.36 | 0.42 | 0.32 | 0.20 | 0.27 | 0.39 / 0.72 | 0.88 | 0 | 5.50 | 19.50 | 17346 |

Recall by error type (found and pointed at the right step):

| Error type | B2v2 8B (fixes) | 70B | B2v2 8B (fixes) screens, 70B confirms |
|---|---|---|---|
| contradicts_tool_result | 0.00 | 0.20 | 0.00 |
| data_leak | 0.00 | 0.50 | 0.17 |
| false_completion | 0.00 | 0.33 | 0.00 |
| hallucinated_fact | 0.33 | 0.83 | 0.50 |
| ignored_tool_error | 0.50 | 0.67 | 0.50 |
| language_mismatch | 0.20 | 0.60 | 0.40 |
| release_without_approval | 0.60 | 0.80 | 0.80 |
| scope_too_small | 0.00 | 0.20 | 0.00 |
| skipped_required_step | 0.40 | 0.60 | 0.40 |
| too_few_first_pieces | 0.00 | 0.00 | 0.00 |
| wrong_order | 0.60 | 0.60 | 0.60 |
| wrong_revision | 0.00 | 1.00 | 0.00 |
| wrong_tool_args | 0.17 | 0.33 | 0.00 |

Two tiers: 64 of 132 traces (48%) reach the confirmer, which then spends 50% of the tokens it would need alone.
