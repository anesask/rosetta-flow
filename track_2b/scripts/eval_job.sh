#!/usr/bin/env bash
# Runs INSIDE the HF Job (vllm/vllm-openai image), started by scripts/hf_eval.sh: serves Apertus 8B with vLLM
# (base model "base", LoRA adapters "auditor-v1" and "auditor-v2"), audits the sets with B0, B1 and B2 (one run
# per adapter), scores them and uploads everything
# to the private dataset repo under eval/NAME/. The job ends when this script ends, so billing stops with it.
# The private dataset repo is mounted read-only at /repo (code/, sets/, scripts/), the adapters at /lora1 to /lora4.
# Args: NAME LIMIT SET... (folder names under /repo/sets; LIMIT 0 = all traces)
set -u
NAME=$1 LIMIT=$2
shift 2
REPO=${REPO:-anesdevtoday/rosetta-flow-sft}
OUT=/tmp/results
mkdir -p "$OUT"
say() { echo "[$(date +%H:%M:%S)] $*"; }

# torchcodec fails to load its native library in this image and crashes vLLM; a text model does not need it.
# The Apertus chat template accepts only string message content ("Invalid system message" otherwise), hence
# --chat-template-content-format string.
pip uninstall -y -q torchcodec >/dev/null 2>&1 || true
say "starting vLLM"
vllm serve andreasmartin/apertus-v1.5-8b-text --served-model-name base --dtype bfloat16 \
    --max-model-len 16384 --gpu-memory-utilization 0.92 --enable-prefix-caching \
    --enable-lora --lora-modules auditor-v1=/lora1 auditor-v2=/lora2 auditor-v3=/lora3 screener-rl=/lora4 \
    --max-lora-rank 16 --max-loras 4 \
    --enable-auto-tool-choice --tool-call-parser apertus --chat-template-content-format string \
    --host 127.0.0.1 --port 8000 > /tmp/vllm.log 2>&1 &
VLLM=$!

say "preparing the harness (Python 3.13 via uv)"
pip install -q uv >/dev/null 2>&1
uv venv -q -p 3.13 /venv && uv pip install -q -p /venv/bin/python openai pydantic python-dotenv regex json-repair huggingface_hub
export PYTHONPATH=/repo/code PYTHONUTF8=1 LLM_BASE_URL=http://127.0.0.1:8000/v1 LLM_API_KEY=local LLM_NAME=base

for _ in $(seq 1 120); do
    curl -sf -o /dev/null http://127.0.0.1:8000/v1/models && break
    kill -0 $VLLM 2>/dev/null || { say "vLLM died"; tail -40 /tmp/vllm.log; exit 1; }
    sleep 10
done
curl -sf http://127.0.0.1:8000/v1/models >/dev/null || { say "vLLM not ready after 20 min"; tail -40 /tmp/vllm.log; exit 1; }
say "vLLM ready: $(curl -s http://127.0.0.1:8000/v1/models | /venv/bin/python -c 'import json,sys; print([m["id"] for m in json.load(sys.stdin)["data"]])')"

upload() {  # after every set, so a timeout loses at most the set in progress
    /venv/bin/python -c "
from huggingface_hub import HfApi
HfApi().upload_folder(repo_id='$REPO', repo_type='dataset', folder_path='$OUT', path_in_repo='eval/$NAME',
                      commit_message='eval $NAME')" && say "uploaded to eval/$NAME"
}

# SYSTEMS (env, space-separated) picks which of B0 B1 B2v1 B2v2 B2v3 to run; B0 B1 B2v1 B2v2 by default.
# S0/S1 are fast screeners (one JSON decision with p_issue, rosetta_flow.screen): base model and the RL adapter.
declare -A MODEL=([B0]=base [B1]=base [B2v1]=auditor-v1 [B2v2]=auditor-v2 [B2v3]=auditor-v3 [S0]=base
                  [S1]=screener-rl)
declare -A MODE=([B0]=single [B1]=investigate [B2v1]=investigate [B2v2]=investigate [B2v3]=investigate [S0]=screen
                 [S1]=screen)
declare -A LABEL=([B0]="B0 8B single prompt" [B1]="B1 8B harness" [B2v1]="B2 v1 8B + LoRA 4-bit 2 ep"
                  [B2v2]="B2 v2 8B + LoRA bf16 3 ep" [B2v3]="B2 v3 8B + LoRA bf16 3 ep + analysis")
LIM=$([ "$LIMIT" -gt 0 ] && echo "--limit $LIMIT" || true)
for S in "$@"; do
    AUDITS=()
    # external sets (tau-bench) bring their own policy and an outcome file instead of span labels
    POL=$([ -f "/repo/sets/$S/policy.md" ] && echo "--policy-file /repo/sets/$S/policy.md" || true)
    for SYS in ${SYSTEMS:-B0 B1 B2v1 B2v2}; do
        say "$SYS on $S"
        if [ "${MODE[$SYS]}" = screen ]; then  # decisions, scored locally against the 70B audits
            /venv/bin/python -m rosetta_flow.screen run --traces "/repo/sets/$S/traces.jsonl" --model "${MODEL[$SYS]}" \
                $POL $LIM --workers 16 --out "$OUT/$S-$SYS" > "$OUT/$S-$SYS.log" 2>&1 || say "$SYS failed"
            tail -1 "$OUT/$S-$SYS.log" | cut -c1-400
            continue
        fi
        /venv/bin/python -m rosetta_flow.harness --traces "/repo/sets/$S/traces.jsonl" --model "${MODEL[$SYS]}" \
            --mode "${MODE[$SYS]}" $POL $LIM --workers 16 --max-tokens 200000000 --out "$OUT/$S-$SYS" \
            > "$OUT/$S-$SYS.log" 2>&1 || say "$SYS failed"
        tail -1 "$OUT/$S-$SYS.log" | cut -c1-400
        AUDITS+=("${LABEL[$SYS]}=$OUT/$S-$SYS/audits.jsonl")
    done
    if [ ${#AUDITS[@]} -gt 0 ] && [ -f "/repo/sets/$S/labels.jsonl" ]; then
        /venv/bin/python -m rosetta_flow.eval --set "/repo/sets/$S" --out "$OUT/eval-$S" $LIM --audits "${AUDITS[@]}" \
            | head -14
    fi
    upload
done

kill $VLLM 2>/dev/null
say "done"
