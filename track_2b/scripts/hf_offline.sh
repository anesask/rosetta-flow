#!/usr/bin/env bash
# Offline proof on Hugging Face: uploads code, the demo runs and scripts/offline/ to the private dataset repo, then
# starts one HF Job (scripts/offline_job.sh) that audits sabotaged runs with a local Apertus 8B after cutting the
# network. About 15 min on an A100 (~$0.70). Run from track_2b:
#   bash scripts/hf_offline.sh refunds-41-0112: refunds-41-0112:wrong_order manufacturing-41-0022:release_without_approval
# Fetch the evidence: .venv/Scripts/hf download anesdevtoday/rosetta-flow-sft --repo-type dataset \
#   --include "offline-proof/*" --local-dir results/hf
set -eu
HF=.venv/Scripts/hf
REPO=${REPO:-anesdevtoday/rosetta-flow-sft}
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"

.venv/Scripts/python - "$REPO" <<'EOF'
import sys
from huggingface_hub import HfApi
repo = sys.argv[1]
api = HfApi()
assert api.dataset_info(repo).private, f"{repo} must stay private"
api.upload_folder(repo_id=repo, repo_type="dataset", folder_path="src/rosetta_flow", path_in_repo="code/rosetta_flow",
                  ignore_patterns=["**/__pycache__/**", "*.pyc", "app/static/**"], commit_message="harness code")
api.upload_folder(repo_id=repo, repo_type="dataset", folder_path="data/demo/live", path_in_repo="demo/live",
                  commit_message="demo runs")
api.upload_folder(repo_id=repo, repo_type="dataset", folder_path="scripts/offline", path_in_repo="offline",
                  ignore_patterns=["**/__pycache__/**"], commit_message="offline proof scripts")
api.upload_file(repo_id=repo, repo_type="dataset", path_or_fileobj="scripts/offline_job.sh",
                path_in_repo="offline/offline_job.sh", commit_message="offline job script")
print("uploaded")
EOF

$HF jobs run --flavor "${FLAVOR:-a100-large}" --timeout 40m --secrets HF_TOKEN --detach --name rosetta-offline-proof \
    -v "hf://datasets/$REPO:/repo" vllm/vllm-openai:v0.31.0-cu129 bash /repo/offline/offline_job.sh "$@" 2>&1 \
    | grep -v Hint
