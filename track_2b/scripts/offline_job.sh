#!/usr/bin/env bash
# Runs INSIDE the HF Job (vllm/vllm-openai image), started by scripts/hf_offline.sh. Proves the auditor needs no
# network at runtime, in three phases:
#   1 ONLINE   install, download the Apertus 8B weights (build time)
#   2 OFFLINE  cut egress, serve the 8B from local files, try the internet (must fail), break and audit demo runs;
#              kernel byte counters: an idle window against the audit window
#   3 ONLINE   upload the evidence (log, counters, audits) to the private dataset repo
# The private dataset repo is mounted read-only at /repo (code/, demo/, offline/). Args: CASE... (RUN_ID:SABOTAGE)
set -u
REPO=${REPO:-anesdevtoday/rosetta-flow-sft}
OUT=/tmp/offline
mkdir -p "$OUT"
exec > >(tee "$OUT/job.log") 2>&1
say() { echo "[$(date +%H:%M:%S)] $*"; }
counters() {  # bytes received and sent per interface, from the kernel
    tail -n +3 /proc/net/dev | awk '{gsub(":", " "); print $1, $2, $10}'
}

say "=== PHASE 1: ONLINE (build time) ==="
pip uninstall -y -q torchcodec >/dev/null 2>&1 || true
pip install -q uv >/dev/null 2>&1
uv venv -q -p 3.13 /venv && uv pip install -q -p /venv/bin/python openai pydantic python-dotenv regex json-repair \
    huggingface_hub
/venv/bin/hf download andreasmartin/apertus-v1.5-8b-text --local-dir /models/apertus-8b >/dev/null 2>&1
say "weights on disk: $(du -sh /models/apertus-8b | cut -f1)"
# /repo is a network mount (hf:// volume): code and data go to local disk before the cut, or reading them is traffic
mkdir -p /opt/rf && cp -r /repo/code /repo/demo /repo/offline /opt/rf/ && say "code and demo runs copied to local disk"
command -v iptables >/dev/null || (apt-get install -y -q iptables >/dev/null 2>&1 || true)

say "=== PHASE 2: OFFLINE (runtime) ==="
FIREWALL="not available"
if iptables -A OUTPUT -o lo -j ACCEPT 2>/dev/null && iptables -A OUTPUT -j REJECT 2>/dev/null; then
    FIREWALL="kernel firewall on: all outbound traffic except loopback rejected"
fi
say "layer 1, $FIREWALL"
export PYTHONPATH=/opt/rf/offline:/opt/rf/code EGRESS_LOG=$OUT/egress_blocked.log
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 VLLM_HOST_IP=127.0.0.1
say "layer 2, egress guard loaded in every Python process; offline flags set"


vllm serve /models/apertus-8b --served-model-name apertus-8b-local --dtype bfloat16 --max-model-len 16384 \
    --gpu-memory-utilization 0.92 --enable-auto-tool-choice --tool-call-parser apertus \
    --chat-template-content-format string --host 127.0.0.1 --port 8000 > "$OUT/vllm.log" 2>&1 &
VLLM=$!
for _ in $(seq 1 90); do
    curl -sf -o /dev/null http://127.0.0.1:8000/v1/models && break
    kill -0 $VLLM 2>/dev/null || { say "vLLM died"; tail -30 "$OUT/vllm.log"; break; }
    sleep 10
done
say "local Apertus 8B serving: $(curl -s http://127.0.0.1:8000/v1/models | head -c 120)"
# Kernel byte counters in two equal-purpose windows: idle (vLLM up, nothing to do) and the audits. Traffic the
# audits cause shows up as a difference; the platform's own background traffic shows up in both.
counters > "$OUT/net_idle_start.txt"; T0=$(date +%s)
sleep 60
counters > "$OUT/net_idle_end.txt"; counters > "$OUT/net_before.txt"; T1=$(date +%s)

PYTHONUTF8=1 LLM_BASE_URL=http://127.0.0.1:8000/v1 LLM_API_KEY=local LLM_NAME=apertus-8b-local \
    /venv/bin/python /opt/rf/offline/proof.py /opt/rf/demo/live "$@"

counters > "$OUT/net_after.txt"; T2=$(date +%s)
kill $VLLM 2>/dev/null; wait $VLLM 2>/dev/null
delta() {
    join "$1" "$2" | awk -v s="$3" '{printf "  %-6s rx %9d B  tx %9d B  (%d s, rx %.0f B/s, tx %.0f B/s)\n",
                                     $1, $4-$2, $5-$3, s, ($4-$2)/s, ($5-$3)/s}'
}
say "layer 3, kernel byte counters per interface:"
echo " idle window (vLLM up, no audit):"; delta "$OUT/net_idle_start.txt" "$OUT/net_idle_end.txt" $((T1-T0)) \
    | tee "$OUT/net_idle.txt"
echo " audit window:"; delta "$OUT/net_before.txt" "$OUT/net_after.txt" $((T2-T1)) | tee "$OUT/net_audit.txt"
say "blocked outbound attempts: $(wc -l < "$OUT/egress_blocked.log" 2>/dev/null || echo 0)"
sort "$OUT/egress_blocked.log" 2>/dev/null | cut -d' ' -f3- | sort | uniq -c | head -10

say "=== PHASE 3: ONLINE (upload the evidence) ==="
[ "$FIREWALL" != "not available" ] && { iptables -F OUTPUT 2>/dev/null || true; }
PYTHONPATH= HF_HUB_OFFLINE=0 /venv/bin/python -c "
from huggingface_hub import HfApi
HfApi().upload_folder(repo_id='$REPO', repo_type='dataset', folder_path='$OUT', path_in_repo='offline-proof-3',
                      commit_message='offline proof 2')" && say "uploaded to offline-proof-3/"
