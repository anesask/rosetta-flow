| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 8B harness | 0.65 | 0.44 | 0.67 | 0.69 | 0.39 | 0.46 | 0.50 / 0.57 | 0.67 | 5 | 3.80 | 19.50 | 11242 |
| B2 v2 8B + LoRA bf16 3 ep | 0.62 | 0.47 | 0.66 | 0.74 | 0.49 | 0.52 | 0.38 / 0.68 | 0.72 | 0 | 3.50 | 10.70 | 9385 |

Recall by error type (found and pointed at the right step):

| Error type | B1 8B harness | B2 v2 8B + LoRA bf16 3 ep |
|---|---|---|
| contradicts_tool_result | 0.57 | 0.29 |
| false_completion | 0.38 | 0.50 |
| hallucinated_fact | 0.11 | 0.00 |
| ignored_tool_error | 0.71 | 0.86 |
| language_mismatch | 0.50 | 0.20 |
| skipped_required_step | 1.00 | 1.00 |
| voucher_over_limit | 0.50 | 0.67 |
| wrong_order | 0.33 | 0.83 |
| wrong_tool_args | 0.17 | 0.83 |
