| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 8B harness | 0.68 | 0.47 | 0.69 | 0.70 | 0.33 | 0.48 | 0.38 / 0.48 | 0.61 | 8 | 4.30 | 25.70 | 13826 |
| B2 v2 8B + LoRA bf16 3 ep | 0.62 | 0.48 | 0.65 | 0.70 | 0.47 | 0.52 | 0.39 / 0.71 | 0.76 | 2 | 3.50 | 12.20 | 10270 |

Recall by error type (found and pointed at the right step):

| Error type | B1 8B harness | B2 v2 8B + LoRA bf16 3 ep |
|---|---|---|
| contradicts_tool_result | 0.71 | 0.43 |
| false_completion | 0.75 | 0.38 |
| hallucinated_fact | 0.25 | 0.12 |
| ignored_tool_error | 0.86 | 0.57 |
| language_mismatch | 0.33 | 0.33 |
| skipped_required_step | 0.50 | 1.00 |
| voucher_over_limit | 0.67 | 0.50 |
| wrong_order | 0.00 | 0.67 |
| wrong_tool_args | 0.17 | 0.83 |
