| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 8B harness | 0.50 | 0.23 | 0.41 | 0.35 | 0.35 | 0.19 | 0.58 / 0.83 | 0.47 | 10 | 4.20 | 31.60 | 17517 |
| B2 v2 8B + LoRA bf16 3 ep | 0.48 | 0.29 | 0.44 | 0.42 | 0.47 | 0.27 | 0.29 / 0.41 | 0.70 | 1 | 3.80 | 12.40 | 12330 |
| B2 v3 8B + LoRA bf16 3 ep + analysis | 0.48 | 0.06 | 0.09 | 0.05 | 0.08 | 0.03 | 0.50 / 0.50 | 0.75 | 2 | 2.70 | 13.20 | 8516 |

Recall by error type (found and pointed at the right step):

| Error type | B1 8B harness | B2 v2 8B + LoRA bf16 3 ep | B2 v3 8B + LoRA bf16 3 ep + analysis |
|---|---|---|---|
| contradicts_tool_result | 0.00 | 0.20 | 0.00 |
| data_leak | 0.17 | 0.17 | 0.17 |
| false_completion | 0.17 | 0.17 | 0.00 |
| hallucinated_fact | 0.40 | 0.20 | 0.00 |
| ignored_tool_error | 0.80 | 0.20 | 0.00 |
| language_mismatch | 0.00 | 0.14 | 0.00 |
| release_without_approval | 0.40 | 1.00 | 0.00 |
| scope_too_small | 0.00 | 0.00 | 0.00 |
| skipped_required_step | 0.20 | 0.40 | 0.00 |
| too_few_first_pieces | 0.00 | 0.00 | 1.00 |
| wrong_order | 0.20 | 0.20 | 0.00 |
| wrong_revision | 0.00 | 0.50 | 0.00 |
| wrong_tool_args | 0.00 | 0.40 | 0.00 |
