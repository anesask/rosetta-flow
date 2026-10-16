| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 8B (fixes) | 0.50 | 0.30 | 0.51 | 0.52 | 0.52 | 0.30 | 0.40 / 0.55 | 0.45 | 11 | 4.40 | 31.10 | 16653 |
| 70B | 0.71 | 0.52 | 0.71 | 0.70 | 0.27 | 0.52 | 0.35 / 0.56 | 0.83 | 0 | 3.60 | 13.70 | 12399 |
| B1 8B (fixes) screens, 70B confirms | 0.64 | 0.43 | 0.55 | 0.44 | 0.17 | 0.35 | 0.30 / 0.61 | 0.88 | 0 | 6.50 | 39.00 | 24158 |

Recall by error type (found and pointed at the right step):

| Error type | B1 8B (fixes) | 70B | B1 8B (fixes) screens, 70B confirms |
|---|---|---|---|
| contradicts_tool_result | 0.20 | 0.20 | 0.20 |
| data_leak | 0.17 | 0.50 | 0.33 |
| false_completion | 0.00 | 0.33 | 0.00 |
| hallucinated_fact | 0.33 | 0.83 | 0.50 |
| ignored_tool_error | 0.67 | 0.67 | 0.67 |
| language_mismatch | 0.20 | 0.60 | 0.40 |
| release_without_approval | 1.00 | 0.80 | 0.80 |
| scope_too_small | 0.00 | 0.20 | 0.00 |
| skipped_required_step | 0.60 | 0.60 | 0.60 |
| too_few_first_pieces | 0.00 | 0.00 | 0.00 |
| wrong_order | 0.60 | 0.60 | 0.60 |
| wrong_revision | 0.00 | 1.00 | 0.33 |
| wrong_tool_args | 0.00 | 0.33 | 0.00 |

Two tiers: 73 of 132 traces (55%) reach the confirmer, which then spends 60% of the tokens it would need alone.
