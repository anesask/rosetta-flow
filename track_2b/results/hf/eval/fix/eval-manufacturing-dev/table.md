| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 8B harness | 0.56 | 0.29 | 0.55 | 0.55 | 0.43 | 0.29 | 0.50 / 0.61 | 0.48 | 14 | 4.30 | 36.10 | 16720 |
| B2 v2 8B + LoRA bf16 3 ep | 0.55 | 0.25 | 0.54 | 0.53 | 0.43 | 0.24 | 0.27 / 0.53 | 0.74 | 2 | 3.80 | 14.10 | 12443 |

Recall by error type (found and pointed at the right step):

| Error type | B1 8B harness | B2 v2 8B + LoRA bf16 3 ep |
|---|---|---|
| contradicts_tool_result | 0.00 | 0.20 |
| data_leak | 0.83 | 0.17 |
| false_completion | 0.33 | 0.33 |
| hallucinated_fact | 0.20 | 0.20 |
| ignored_tool_error | 0.40 | 0.40 |
| language_mismatch | 0.14 | 0.29 |
| release_without_approval | 0.60 | 0.60 |
| scope_too_small | 0.00 | 0.00 |
| skipped_required_step | 0.40 | 0.00 |
| too_few_first_pieces | 0.00 | 0.00 |
| wrong_order | 0.20 | 0.20 |
| wrong_revision | 0.00 | 0.00 |
| wrong_tool_args | 0.20 | 0.40 |
