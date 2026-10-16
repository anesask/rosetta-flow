| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 8B harness | 0.50 | 0.30 | 0.51 | 0.52 | 0.52 | 0.30 | 0.40 / 0.55 | 0.45 | 11 | 4.40 | 31.10 | 16653 |
| B2 v2 8B + LoRA bf16 3 ep | 0.42 | 0.23 | 0.41 | 0.41 | 0.56 | 0.23 | 0.20 / 0.53 | 0.77 | 1 | 3.60 | 12.20 | 11103 |

Recall by error type (found and pointed at the right step):

| Error type | B1 8B harness | B2 v2 8B + LoRA bf16 3 ep |
|---|---|---|
| contradicts_tool_result | 0.20 | 0.00 |
| data_leak | 0.17 | 0.00 |
| false_completion | 0.00 | 0.00 |
| hallucinated_fact | 0.33 | 0.33 |
| ignored_tool_error | 0.67 | 0.50 |
| language_mismatch | 0.20 | 0.20 |
| release_without_approval | 1.00 | 0.60 |
| scope_too_small | 0.00 | 0.00 |
| skipped_required_step | 0.60 | 0.40 |
| too_few_first_pieces | 0.00 | 0.00 |
| wrong_order | 0.60 | 0.60 |
| wrong_revision | 0.00 | 0.00 |
| wrong_tool_args | 0.00 | 0.17 |
