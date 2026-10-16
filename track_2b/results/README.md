# results: where each number in the report comes from

Each folder holds `summary.json` / `table.md` (score tables) and, for the harness runs, per-trace audit summaries.
Raw transcripts and generated runs are not in git (size); they are in the published dataset. Commands:
[`docs/reproduce.md`](../docs/reproduce.md).

## Report tables

| Report section | Folders |
|---|---|
| 5.1 held-out test, B0 / B1 / B2 (8B systems on vLLM) | `hf/eval/test/` (job output; B1 and v2 after the harness fixes in `cascade2-*-test-B1`, `cascade2-*-test-B2v2`) |
| 5.1 held-out test, B3 (70B) | `refunds-test-B3/`, `manufacturing-test-B3/` (+ `.log`) |
| 5.1 two tiers (B1 screens, B3 confirms), final | `cascade2-refunds-test-B1/`, `cascade2-manufacturing-test-B1/` |
| 5.1 two tiers, first independent measurement (before the harness fixes) | `cascade-refunds-test-B1/`, `cascade-manufacturing-test-B1/` (and `-v2` with the LoRA screener) |
| 5.1 on own hardware (A100 seconds per run) | `hf/eval/test/` timing in `summary.json` |
| 5.2 investigating vs verify confirmer (dev) | `cascade-audit-*-dev/` vs `cascade-verify-*-dev/`, `verify-*-dev/` |
| 5.3 fine-tuning on dev (B1, v2, v3) | `hf/eval/dev/`; 8B re-runs after the harness fixes in `hf/eval/fix/`, `hf/eval/fix2/` |
| 5.4 GRPO single-pass screener | `screen-dev-*-S0.json`, `screen-dev-*-S1.json`, raw in `hf/eval/screen-dev/` |
| 5.5 tau-bench airline | `taubench-airline-B3/` (+ `.log`), 8B and two tiers in `hf/eval/tau/`; manual review `taubench-review/` |
| 2 offline run | `offline-proof/` (`net_idle.txt`, `net_audit.txt`, `egress_blocked.log`, `audits.json`, `job.log`) |

## Development history

The dev-set runs behind the harness decisions (ablations, harness versions v6 to v9) are not in the repo;
they are summarised in the report and available on request.

Run-to-run variation at 120 to 130 runs per set is about 0.03 to 0.05 in balanced accuracy; dev decisions were
taken on two runs each.
