"""QLoRA SFT of Apertus 8B on the gold investigations (Kaggle T4 x2: 4-bit base, fp16, layers on both GPUs).

Standalone on purpose: upload this file and data/sft/train.jsonl to Kaggle, no rosetta_flow install needed.
Only the auditor's own moves carry loss: text after <|assistant_start|> or <|tool_output_end|> up to and including
<|tools_suffix|> (or <|assistant_end|>). System prompt, task and tool outputs are context. The Apertus template has
no generation markers and renders a whole tool loop as one assistant block, so TRL's assistant-only loss cannot
do this.

pip install -U "transformers>=4.56" peft bitsandbytes accelerate
python qlora.py --data train.jsonl --out adapter [--limit 40 --max-steps 20]   # pipeline check
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
from pathlib import Path

TURN_STARTS = ("<|assistant_start|>", "<|tool_output_end|>")
TURN_ENDS = ("<|tools_suffix|>", "<|assistant_end|>")


def trainable_spans(text: str) -> list[tuple[int, int]]:
    """Character ranges the model itself writes in a rendered conversation (end markers included)."""
    spans: list[tuple[int, int]] = []
    pos = 0
    while True:
        hits = [(i, m) for m in TURN_STARTS if (i := text.find(m, pos)) >= 0]
        if not hits:
            return spans
        i, m = min(hits)
        start = i + len(m)
        ends = [j + len(e) for e in TURN_ENDS if (j := text.find(e, start)) >= 0]
        end = min(ends) if ends else len(text)
        if end > start:
            spans.append((start, end))
        pos = end


def token_labels(offsets: list[tuple[int, int]], input_ids: list[int], spans: list[tuple[int, int]]) -> list[int]:
    labels = [-100] * len(input_ids)
    k = 0
    for t, (a, _b) in enumerate(offsets):
        while k < len(spans) and spans[k][1] <= a:
            k += 1
        if k < len(spans) and spans[k][0] <= a < spans[k][1]:
            labels[t] = input_ids[t]
    return labels


def encode(tokenizer, example: dict) -> dict:
    text = tokenizer.apply_chat_template(example["messages"], tools=example["tools"], tokenize=False)
    enc = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)  # the template adds <s>
    ids = enc["input_ids"]
    labels = token_labels(enc["offset_mapping"], ids, trainable_spans(text))
    return {"input_ids": ids, "labels": labels, "trace_id": example.get("trace_id", "")}


def diagnose(model, example: dict, dtype_name: str) -> None:
    """Forward one example through the untrained model; name the first module whose output is not finite."""
    import torch

    peaks: dict[str, float] = {}
    first_bad: list[str] = []

    def hook(name):
        def record(_mod, _inp, out):
            t = out[0] if isinstance(out, tuple) else out
            if torch.is_tensor(t) and t.is_floating_point():
                peak = t.detach().float().abs().max().item()
                peaks[name] = peak
                if not math.isfinite(peak) and not first_bad:
                    first_bad.append(name)

        return record

    handles = [m.register_forward_hook(hook(n)) for n, m in model.named_modules() if n]
    ids = torch.tensor([example["input_ids"]], device=model.device)
    labels = torch.tensor([example["labels"]], device=model.device)
    try:
        with torch.no_grad():
            loss = model(input_ids=ids, labels=labels).loss.item()
    except Exception as e:  # e.g. a dtype the GPU cannot run
        loss = f"{type(e).__name__}: {e}"
    for h in handles:
        h.remove()
    layers = {n: v for n, v in peaks.items() if n.rsplit(".", 1)[-1].isdigit()}
    print(json.dumps({
        "compute_dtype": dtype_name,
        "tokens": len(example["input_ids"]),
        "loss": loss,
        "first_non_finite_module": first_bad[0] if first_bad else None,
        "layer_output_peaks": {n.rsplit(".", 1)[-1]: round(v, 1) for n, v in layers.items()},
        "largest_module_outputs": sorted(((round(v, 1), n) for n, v in peaks.items() if math.isfinite(v)),
                                         reverse=True)[:12],
    }, indent=1))  # fmt: skip


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", type=Path, required=True, help="SFT jsonl from rosetta_flow.train.sft")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--model", default="andreasmartin/apertus-v1.5-8b-text")
    p.add_argument("--max-len", type=int, default=8192, help="longer examples are dropped, never truncated")
    p.add_argument("--limit", type=int, default=0, help="use only the first N examples (pipeline check)")
    p.add_argument("--epochs", type=float, default=2)
    p.add_argument("--max-steps", type=int, default=-1)
    p.add_argument("--lr", type=float, default=1e-4)
    p.add_argument("--rank", type=int, default=16)
    p.add_argument("--grad-accum", type=int, default=8)
    p.add_argument("--eval-frac", type=float, default=0.05)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--gpu-mem-gib", type=int, default=9, help="weights per GPU; the rest is for activations")
    p.add_argument("--no-quant", action="store_true", help="LoRA on the bf16 model instead of 4 bit (big GPUs)")
    p.add_argument("--batch", type=int, default=1, help="examples per device step; effective batch = batch * accum")
    # Apertus has activations of ~118k from layer 3 on: fp16 (max 65504) overflows, bf16 holds them (checked on T4)
    p.add_argument("--compute-dtype", choices=["float16", "bfloat16", "float32"], default="bfloat16")
    p.add_argument("--diagnose", action="store_true", help="one forward pass of the base model, report overflows")
    args = p.parse_args()

    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")  # must precede the torch import
    # Job logs are not a terminal: every progress-bar refresh becomes a new line.
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        PrinterCallback,
        Trainer,
        TrainerCallback,
        TrainingArguments,
    )
    from transformers.utils import logging as hf_logging

    hf_logging.disable_progress_bar()
    hf_logging.set_verbosity_error()

    t0 = time.time()

    def say(msg: str) -> None:
        s = int(time.time() - t0)
        print(f"[{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}] {msg}", flush=True)

    class StepLog(TrainerCallback):
        def on_train_begin(self, _args, state, _control, **_kw):
            self.start = time.time()
            say(f"training: {state.max_steps} steps")

        def on_log(self, _args, state, _control, logs=None, **_kw):
            logs = logs or {}
            if "loss" in logs:
                per_step = (time.time() - self.start) / max(1, state.global_step)
                eta = int(per_step * (state.max_steps - state.global_step))
                say(f"step {state.global_step:>3}/{state.max_steps}  loss {logs['loss']:.4f}  "
                    f"grad {logs.get('grad_norm', float('nan')):.3f}  lr {logs.get('learning_rate', 0):.1e}  "
                    f"{per_step:.0f} s/step  eta {eta // 60} min")  # fmt: skip
            if "eval_loss" in logs:
                say(f"eval  loss {logs['eval_loss']:.4f}  (epoch {logs.get('epoch', 0):.1f})")

    say(f"loading tokenizer and data ({args.model})")
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    rows = [json.loads(line) for line in args.data.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        rows = rows[: args.limit]
    encoded = [encode(tokenizer, r) for r in rows]
    kept = [e for e in encoded if len(e["input_ids"]) <= args.max_len and any(x != -100 for x in e["labels"])]
    lengths = sorted(len(e["input_ids"]) for e in kept)
    stats = {
        "examples": len(rows),
        "kept": len(kept),
        "dropped_too_long": sum(len(e["input_ids"]) > args.max_len for e in encoded),
        "tokens_median": lengths[len(lengths) // 2] if lengths else 0,
        "tokens_max": lengths[-1] if lengths else 0,
        "trained_token_share": round(sum(sum(x != -100 for x in e["labels"]) for e in kept) / max(1, sum(lengths)), 3),
    }
    say(f"data: {json.dumps(stats)}")
    random.Random(args.seed).shuffle(kept)
    n_eval = max(1, int(len(kept) * args.eval_frac)) if len(kept) > 20 else 0
    eval_set, train_set = kept[:n_eval], kept[n_eval:]

    dtype = getattr(torch, args.compute_dtype)
    gpus = ", ".join(torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count()))
    say(f"loading model {'unquantized' if args.no_quant else 'in 4 bit'}, compute {args.compute_dtype}, GPUs: {gpus}")
    # --no-quant trains on the same bf16 weights vLLM serves; 4 bit only where memory forces it (T4, L4).
    quant = None if args.no_quant else BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=dtype,
    )  # fmt: skip
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=quant,
        dtype=dtype,
        # Layers split over all GPUs (Kaggle: 2x T4); the cap leaves room for activations and 131k-vocab logits.
        device_map="auto",
        max_memory={i: f"{args.gpu_mem_gib}GiB" for i in range(torch.cuda.device_count())},
    )  # fmt: skip
    if args.diagnose:
        diagnose(model, kept[0], args.compute_dtype)
        return
    # No prepare_model_for_kbit_training: it upcasts embeddings and lm_head to fp32 (+2 GB) and the T4 runs out.
    # PEFT keeps the adapters in fp32 itself; checkpointing needs grads on the inputs.
    model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(
        r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.05, target_modules="all-linear", task_type="CAUSAL_LM",
    ))  # fmt: skip
    trainable, total = model.get_nb_trainable_parameters()
    say(f"LoRA r={args.rank}: {trainable / 1e6:.1f}M trainable of {total / 1e9:.2f}B")

    def collate(batch: list[dict]) -> dict:
        width = max(len(b["input_ids"]) for b in batch)
        pad = tokenizer.pad_token_id
        ids = [b["input_ids"] + [pad] * (width - len(b["input_ids"])) for b in batch]
        labels = [b["labels"] + [-100] * (width - len(b["labels"])) for b in batch]
        mask = [[1] * len(b["input_ids"]) + [0] * (width - len(b["input_ids"])) for b in batch]
        return {"input_ids": torch.tensor(ids), "labels": torch.tensor(labels), "attention_mask": torch.tensor(mask)}

    strip = [{"input_ids": e["input_ids"], "labels": e["labels"]} for e in train_set]
    # warmup_ratio was removed in transformers v5; an explicit step count works in every version
    per_step = args.batch * args.grad_accum
    steps = args.max_steps if args.max_steps > 0 else math.ceil(len(strip) / per_step * args.epochs)
    trainer = Trainer(
        model=model,
        train_dataset=strip,
        eval_dataset=[{"input_ids": e["input_ids"], "labels": e["labels"]} for e in eval_set] or None,
        data_collator=collate,
        args=TrainingArguments(
            output_dir=str(args.out / "checkpoints"),
            per_device_train_batch_size=args.batch,
            per_device_eval_batch_size=1,
            gradient_accumulation_steps=args.grad_accum,
            num_train_epochs=args.epochs,
            max_steps=args.max_steps,
            learning_rate=args.lr,
            lr_scheduler_type="cosine",
            warmup_steps=max(1, round(0.05 * steps)),
            fp16=args.compute_dtype == "float16",
            bf16=False,  # no autocast: the model already computes in bf16, which needs no grad scaler
            gradient_checkpointing=True,
            gradient_checkpointing_kwargs={"use_reentrant": False},
            logging_steps=1,
            eval_strategy="epoch" if eval_set else "no",
            save_strategy="epoch",
            save_total_limit=1,
            remove_unused_columns=False,
            report_to="none",
            disable_tqdm=True,
            seed=args.seed,
        ),
        callbacks=[StepLog()],
    )
    trainer.remove_callback(PrinterCallback)  # it prints raw log dicts; StepLog prints one line per step
    trainer.train()
    model.save_pretrained(args.out / "adapter")
    tokenizer.save_pretrained(args.out / "adapter")
    say(f"adapter saved to {args.out / 'adapter'}; smoke test on a held-out trace")

    # Smoke test: the first move on a held-out trace must be a native tool call.
    probe = next((r for r in rows if r.get("trace_id") == (eval_set or train_set)[0]["trace_id"]), rows[0])
    prompt = tokenizer.apply_chat_template(probe["messages"][:2], tools=probe["tools"], tokenize=False,
                                           add_generation_prompt=True)  # fmt: skip
    model.eval()
    with torch.no_grad():
        inp = tokenizer(prompt, add_special_tokens=False, return_tensors="pt").to(model.device)
        out = model.generate(**inp, max_new_tokens=200, do_sample=False)
    first_move = tokenizer.decode(out[0][inp["input_ids"].shape[1] :], skip_special_tokens=False)
    say(f"first move: {first_move[:300]}")

    log = {
        "args": {k: str(v) for k, v in vars(args).items()},
        "data": stats,
        "train_examples": len(train_set),
        "eval_examples": len(eval_set),
        "history": trainer.state.log_history,
        "first_move": first_move,
        "first_move_is_tool_call": "<|tools_prefix|>" in first_move,
        "minutes": round((time.time() - t0) / 60, 1),
    }
    (args.out / "train_log.json").write_text(json.dumps(log, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {k: log[k] for k in ("train_examples", "eval_examples", "first_move_is_tool_call", "minutes")}
    say(f"done: {json.dumps(summary)}")


if __name__ == "__main__":
    main()
