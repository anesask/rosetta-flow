#!/usr/bin/env bash
# QLoRA training of Apertus 8B as a Hugging Face Job (L4: bf16 in hardware; the Kaggle T4s only emulate it).
# Data and qlora.py come from the private dataset repo; adapter and log go to the private model repo under RUN.
# The container is thrown away after the job, so pip may install into its system Python.
# Run from track_2b: [FLAVOR=l4x1] bash scripts/hf_train.sh RUN TIMEOUT [qlora.py args...]
#   bash scripts/hf_train.sh test-2steps 25m --limit 40 --max-steps 2
set -eu
RUN=$1 TIMEOUT=$2
shift 2
DATA_REPO=${DATA_REPO:-anesdevtoday/rosetta-flow-sft}
OUT_REPO=${OUT_REPO:-anesdevtoday/rosetta-flow-auditor-lora}
IMAGE=pytorch/pytorch:2.13.0-cuda12.6-cudnn9-runtime

.venv/Scripts/hf jobs run --flavor "${FLAVOR:-l4x1}" --timeout "$TIMEOUT" --secrets HF_TOKEN --detach "$IMAGE" bash -c "
set -e
export HF_HUB_DISABLE_PROGRESS_BARS=1
echo '== install'
# spin (preinstalled in the image, unused) pins an older click than huggingface_hub needs: drop it so pip does not
# warn; pinning click instead breaks the hf CLI
pip uninstall -y -q --break-system-packages spin > /dev/null 2>&1 || true
pip install -q --break-system-packages --root-user-action=ignore 'transformers>=4.56' peft bitsandbytes accelerate huggingface_hub
echo '== data'
# hf prints update hints and the target path: keep its output only for failures
hf download $DATA_REPO --repo-type dataset --local-dir /data --quiet > /tmp/hf.log 2>&1 || { cat /tmp/hf.log; exit 1; }
echo '== train ($RUN)'
python -u /data/qlora.py --data /data/train.jsonl --out /out --gpu-mem-gib 20 $*
echo '== upload'
hf upload $OUT_REPO /out/adapter $RUN/adapter --commit-message '$RUN adapter' --quiet > /tmp/hf.log 2>&1 || { cat /tmp/hf.log; exit 1; }
hf upload $OUT_REPO /out/train_log.json $RUN/train_log.json --commit-message '$RUN log' --quiet > /tmp/hf.log 2>&1 || { cat /tmp/hf.log; exit 1; }
echo '== done'
"
