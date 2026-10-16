| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 8B harness | 0.66 | 0.48 | 0.65 | 0.63 | 0.32 | 0.47 | 0.54 / 0.64 | 0.66 | 5 | 4.10 | 27.20 | 14409 |
| B2 v2 8B + LoRA bf16 3 ep | 0.59 | 0.49 | 0.65 | 0.75 | 0.57 | 0.57 | 0.38 / 0.73 | 0.78 | 4 | 3.70 | 13.90 | 11076 |

Recall by error type (found and pointed at the right step):

| Error type | B1 8B harness | B2 v2 8B + LoRA bf16 3 ep |
|---|---|---|
| contradicts_tool_result | 0.43 | 0.43 |
| false_completion | 0.50 | 0.38 |
| hallucinated_fact | 0.12 | 0.00 |
| ignored_tool_error | 0.57 | 0.57 |
| language_mismatch | 0.67 | 0.50 |
| skipped_required_step | 1.00 | 0.83 |
| voucher_over_limit | 0.50 | 0.83 |
| wrong_order | 0.33 | 1.00 |
| wrong_tool_args | 0.17 | 0.83 |
