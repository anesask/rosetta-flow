# rosetta-flow: reproducing the numbers

Every table in the technical report comes from a folder under [`results/`](../results/README.md). This page lists
the commands that produced them. Hardware: a laptop for the harness against the CSCS API; Hugging Face Jobs with
one L4 (LoRA v1) or one A100 80 GB (LoRA v2/v3, GRPO, vLLM evaluation of the 8B systems, offline proof). Every job
has a hard timeout and is resumable. Model config is read only from `LLM_NAME`, `LLM_BASE_URL`, `LLM_API_KEY`.

## Data

```bash
bash scripts/make_splits.sh                       # simulate + inject: train / dev / test, seeds in the report
python -m rosetta_flow.train.gold                 # 70B reference investigations, rejection sampling
python -m rosetta_flow.train.sft --balance [--analysis]   # SFT examples (v3 keeps the 70B's analysis)
```

## Training (Hugging Face Jobs)

```bash
bash scripts/hf_train.sh RUN TIMEOUT [qlora.py args]      # LoRA SFT: v1 default 4-bit nf4; v2/v3 --no-quant --epochs 3
bash scripts/hf_rl.sh RUN TIMEOUT                         # GRPO single-pass screener (section 5.4)
```

The scripts upload data to and write results into the author's Hugging Face repos; set `REPO` (or `DATA_REPO` and
`OUT_REPO`) to your own. The published adapters and data are on
[rosetta-flow-auditor-lora](https://huggingface.co/anesdevtoday/rosetta-flow-auditor-lora) and
[rosetta-flow-traces](https://huggingface.co/datasets/anesdevtoday/rosetta-flow-traces).

Apertus produces activations of about 118,000 from layer 3 on, which overflows fp16 (max 65,504) and gave NaN
losses on T4 GPUs; train in bf16 on L4 or A100.

## Evaluation

```bash
bash scripts/hf_eval.sh NAME TIMEOUT 0 refunds-test manufacturing-test     # B0, B1, B2 on vLLM (8B + adapters)
python -m rosetta_flow.harness --traces data/sets/refunds-test --model swiss-ai/Apertus-v1.5-70B --out results/refunds-test-B3   # B3
python -m rosetta_flow.eval.cascade --set refunds-test --screener <B1 audits> --confirmer <B3 audits>   # two tiers, computed
python -m rosetta_flow.pipeline --traces data/sets/refunds-test --config pipeline.toml                  # two tiers, live
python -m rosetta_flow.screen build|run|score ...                                                        # single-pass screener S0 / S1
```

vLLM v0.31 flags that matter (`scripts/eval_job.sh`): `--tool-call-parser apertus`,
`--chat-template-content-format string` (the Apertus template accepts only string message content),
`--max-model-len 16384` (fails on the longest tau-bench runs; a larger GPU allows 32k).

## External runs (tau-bench)

```bash
python -m rosetta_flow.gen.taubench convert --input gpt-4o-airline.json --domain airline --out data/sets/taubench-airline
python -m rosetta_flow.harness --traces data/sets/taubench-airline --model swiss-ai/Apertus-v1.5-70B
python -m rosetta_flow.gen.taubench score ...
```

## Offline proof

`bash scripts/hf_offline.sh` runs one GPU job in three phases (download, audit offline behind an egress guard
with kernel byte counters, upload evidence). Evidence and the counter log: `results/offline-proof/`.

## Tests

`pytest` runs 69 offline tests (no network), including the security tests: prompt-injection fence, ReDoS limit,
JSON fuzzing, tamper-evident review log.
