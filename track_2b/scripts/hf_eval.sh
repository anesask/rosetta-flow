#!/usr/bin/env bash
# Evaluate the on-prem auditor entirely on Hugging Face: uploads the harness code, the sets and scripts/eval_job.sh
# to the private dataset repo, then starts one HF Job that serves Apertus 8B (+ our LoRA adapter) with vLLM, runs
# B0/B1/B2, scores them and uploads the results to eval/NAME/ in that repo. The local PC is free while it runs.
# Run from track_2b: [FLAVOR=a100-large] [SYSTEMS="B0 B1 B2v2"] bash scripts/hf_eval.sh NAME TIMEOUT LIMIT SET...
#   bash scripts/hf_eval.sh smoke 45m 10 refunds-dev manufacturing-dev
#   bash scripts/hf_eval.sh test 3h 0 refunds-test manufacturing-test     (LIMIT 0 = all traces)
# Fetch results: .venv/Scripts/hf download anesdevtoday/rosetta-flow-sft --repo-type dataset \
#   --include "eval/NAME/*" --local-dir results/hf
set -eu
NAME=$1 TIMEOUT=$2 LIMIT=$3
shift 3
HF=.venv/Scripts/hf
REPO=${REPO:-anesdevtoday/rosetta-flow-sft}
ADAPTERS=hf://anesdevtoday/rosetta-flow-auditor-lora  # v1: full-2ep (4-bit), v2: full-3ep-bf16, v3: + analysis
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
# Git Bash would rewrite container paths like /lora into C:/Program Files/Git/lora
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"

for S in "$@"; do [ -f "data/sets/$S/traces.jsonl" ] || { echo "no set data/sets/$S"; exit 1; }; done
echo "uploading code, sets and job script to $REPO (private)"
.venv/Scripts/python - "$REPO" "$@" <<'EOF'
import sys
from huggingface_hub import HfApi
repo, sets = sys.argv[1], sys.argv[2:]
api = HfApi()
assert api.dataset_info(repo).private, f"{repo} must stay private"
api.upload_folder(repo_id=repo, repo_type="dataset", folder_path="src/rosetta_flow", path_in_repo="code/rosetta_flow",
                  ignore_patterns=["**/__pycache__/**", "*.pyc", "app/**"], commit_message="harness code")
api.upload_file(repo_id=repo, repo_type="dataset", path_or_fileobj="scripts/eval_job.sh",
                path_in_repo="scripts/eval_job.sh", commit_message="eval job script")
for s in sets:
    api.upload_folder(repo_id=repo, repo_type="dataset", folder_path=f"data/sets/{s}", path_in_repo=f"sets/{s}",
                      allow_patterns=["traces.jsonl", "labels.jsonl", "outcomes.jsonl", "policy.md", "manifest.json"],
                      commit_message=f"set {s}")
print("uploaded")
EOF

ENV=()
[ -n "${SYSTEMS:-}" ] && ENV=(-e "SYSTEMS=$SYSTEMS")  # e.g. SYSTEMS="B0 B1 B2v2"; default: all four
$HF jobs run --flavor "${FLAVOR:-a100-large}" --timeout "$TIMEOUT" --secrets HF_TOKEN --detach "${ENV[@]}" \
    --name "rosetta-eval-$NAME" -v "$ADAPTERS/full-2ep/adapter:/lora1" \
    -v "$ADAPTERS/full-3ep-bf16/adapter:/lora2" -v "$ADAPTERS/full-3ep-bf16-analysis/adapter:/lora3" \
    -v "$ADAPTERS/${RL_RUN:-rl-screener-v1}/adapter:/lora4" \
    -v "hf://datasets/$REPO:/repo" \
    vllm/vllm-openai:v0.31.0-cu129 bash /repo/scripts/eval_job.sh "$NAME" "$LIMIT" "$@" 2>&1 | grep -v Hint
