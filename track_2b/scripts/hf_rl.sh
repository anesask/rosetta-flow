#!/usr/bin/env bash
# GRPO for the calibrated screener as a Hugging Face Job: rl.py and data/rl/train.jsonl go to the private dataset
# repo under rl/, the adapter and log to the private model repo under RUN. The container is thrown away after
# the job, so pip may install into its system Python.
# Run from track_2b: [FLAVOR=a100-large] bash scripts/hf_rl.sh RUN TIMEOUT [rl.py args...]
#   bash scripts/hf_rl.sh rl-check 25m --limit 16 --max-steps 2
set -eu
RUN=$1 TIMEOUT=$2
shift 2
DATA_REPO=${DATA_REPO:-anesdevtoday/rosetta-flow-sft}
OUT_REPO=${OUT_REPO:-anesdevtoday/rosetta-flow-auditor-lora}
IMAGE=pytorch/pytorch:2.13.0-cuda12.6-cudnn9-runtime
export PYTHONUTF8=1 MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*"

.venv/Scripts/python - "$DATA_REPO" <<'EOF'
import sys
from huggingface_hub import HfApi
api, repo = HfApi(), sys.argv[1]
assert api.dataset_info(repo).private, f"{repo} must stay private"
api.upload_file(path_or_fileobj="src/rosetta_flow/train/rl.py", path_in_repo="rl/rl.py", repo_id=repo,
                repo_type="dataset", commit_message="rl script")
api.upload_file(path_or_fileobj="data/rl/train.jsonl", path_in_repo="rl/train.jsonl", repo_id=repo,
                repo_type="dataset", commit_message="rl prompts")
print("uploaded rl.py and train.jsonl")
EOF

.venv/Scripts/hf jobs run --flavor "${FLAVOR:-a100-large}" --timeout "$TIMEOUT" --secrets HF_TOKEN --detach \
    --name "rosetta-$RUN" "$IMAGE" bash -c "
set -e
export HF_HUB_DISABLE_PROGRESS_BARS=1
echo '== install'
# spin (preinstalled in the image, unused) pins an older click than huggingface_hub needs: drop it so pip does not
# warn; pinning click instead breaks the hf CLI
pip uninstall -y -q --break-system-packages spin > /dev/null 2>&1 || true
pip install -q --break-system-packages --root-user-action=ignore 'transformers>=4.56' peft trl datasets accelerate \
    huggingface_hub
python -c 'import trl, transformers, peft; print(\"trl\", trl.__version__, \"transformers\", transformers.__version__)'
echo '== data'
# hf prints update hints and the target path: keep its output only for failures
hf download $DATA_REPO --repo-type dataset --include 'rl/*' --local-dir /data --quiet > /tmp/hf.log 2>&1 || { cat /tmp/hf.log; exit 1; }
echo '== train ($RUN)'
python -u /data/rl/rl.py --data /data/rl/train.jsonl --out /out $*
echo '== upload'
hf upload $OUT_REPO /out/adapter $RUN/adapter --commit-message '$RUN adapter' --quiet > /tmp/hf.log 2>&1 || { cat /tmp/hf.log; exit 1; }
hf upload $OUT_REPO /out/train_log.json $RUN/train_log.json --commit-message '$RUN log' --quiet > /tmp/hf.log 2>&1 || { cat /tmp/hf.log; exit 1; }
echo '== done'
" 2>&1 | grep -v Hint
