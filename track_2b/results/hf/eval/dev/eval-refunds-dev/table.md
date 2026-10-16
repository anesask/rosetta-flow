| System | Balanced acc. | Strict F1 | Detection F1 | Recall | False alarms | Right step | Type (strict/lenient) | Evidence verified | Failed audits | Tool calls | s / trace | Tokens / trace |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B1 8B harness | 0.66 | 0.46 | 0.65 | 0.63 | 0.32 | 0.45 | 0.41 / 0.52 | 0.61 | 10 | 3.10 | 20.00 | 10068 |
| B2 v2 8B + LoRA bf16 3 ep | 0.60 | 0.51 | 0.64 | 0.72 | 0.52 | 0.57 | 0.38 / 0.71 | 0.73 | 2 | 3.40 | 12.10 | 9521 |
| B2 v3 8B + LoRA bf16 3 ep + analysis | 0.56 | 0.20 | 0.25 | 0.15 | 0.03 | 0.12 | 0.43 / 0.57 | 0.93 | 0 | 2.30 | 9.20 | 5584 |

Recall by error type (found and pointed at the right step):

| Error type | B1 8B harness | B2 v2 8B + LoRA bf16 3 ep | B2 v3 8B + LoRA bf16 3 ep + analysis |
|---|---|---|---|
| contradicts_tool_result | 0.14 | 0.57 | 0.00 |
| false_completion | 0.62 | 0.62 | 0.25 |
| hallucinated_fact | 0.25 | 0.12 | 0.00 |
| ignored_tool_error | 0.57 | 0.57 | 0.00 |
| language_mismatch | 0.67 | 0.33 | 0.00 |
| skipped_required_step | 0.67 | 0.83 | 0.50 |
| voucher_over_limit | 0.83 | 0.50 | 0.17 |
| wrong_order | 0.00 | 1.00 | 0.17 |
| wrong_tool_args | 0.33 | 0.67 | 0.00 |
