| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 8B single prompt | 0.52 | 0.20 | 0.66 | 0.92 | 0.89 | 0.29 | 0.42 / 0.47 | 0.21 | 4 | 0.00 | 4.10 | 2408 |
| B1 8B harness | 0.54 | 0.33 | 0.52 | 0.50 | 0.42 | 0.32 | 0.38 / 0.52 | 0.57 | 15 | 4.00 | 33.00 | 18040 |
| B2 v2 8B + LoRA bf16 3 ep | 0.52 | 0.27 | 0.52 | 0.53 | 0.50 | 0.27 | 0.17 / 0.44 | 0.79 | 1 | 3.50 | 11.00 | 10819 |

Recall by error type (found and pointed at the right step):

| Error type | B0 8B single prompt | B1 8B harness | B2 v2 8B + LoRA bf16 3 ep |
|---|---|---|---|
| contradicts_tool_result | 0.20 | 0.20 | 0.00 |
| data_leak | 0.33 | 0.50 | 0.17 |
| false_completion | 0.17 | 0.17 | 0.00 |
| hallucinated_fact | 0.00 | 0.33 | 0.17 |
| ignored_tool_error | 0.17 | 0.50 | 0.33 |
| language_mismatch | 0.00 | 0.00 | 0.20 |
| release_without_approval | 0.60 | 0.80 | 0.80 |
| scope_too_small | 0.00 | 0.00 | 0.00 |
| skipped_required_step | 0.20 | 0.20 | 0.40 |
| too_few_first_pieces | 1.00 | 0.00 | 0.00 |
| wrong_order | 0.20 | 0.40 | 0.60 |
| wrong_revision | 0.00 | 0.33 | 0.00 |
| wrong_tool_args | 1.00 | 0.50 | 0.67 |
