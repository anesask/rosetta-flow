| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 8B harness | 0.59 | 0.26 | 0.58 | 0.56 | 0.39 | 0.26 | 0.31 / 0.62 | 0.47 | 8 | 4.50 | 33.30 | 18305 |
| B2 v2 8B + LoRA bf16 3 ep | 0.56 | 0.23 | 0.55 | 0.53 | 0.40 | 0.23 | 0.36 / 0.57 | 0.67 | 4 | 4.20 | 15.80 | 14201 |

Recall by error type (found and pointed at the right step):

| Error type | B1 8B harness | B2 v2 8B + LoRA bf16 3 ep |
|---|---|---|
| contradicts_tool_result | 0.20 | 0.20 |
| data_leak | 0.17 | 0.17 |
| false_completion | 0.33 | 0.17 |
| hallucinated_fact | 0.40 | 0.20 |
| ignored_tool_error | 0.20 | 0.20 |
| language_mismatch | 0.14 | 0.14 |
| release_without_approval | 1.00 | 0.40 |
| scope_too_small | 0.00 | 0.00 |
| skipped_required_step | 0.20 | 0.40 |
| too_few_first_pieces | 0.00 | 0.00 |
| wrong_order | 0.40 | 0.20 |
| wrong_revision | 0.00 | 0.00 |
| wrong_tool_args | 0.00 | 0.60 |
