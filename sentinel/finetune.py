"""QLoRA fine-tune of the Sentinel SLM. Designed for a free Colab T4 GPU.

    pip install unsloth trl datasets
    python sentinel/finetune.py --base unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit --data sentinel/sft --out sentinel/outputs

Then export for the phone (llama.cpp GGUF, 4-bit) with --export-gguf.
The LoRA update: W = W0 + (alpha / r) * B A, with W0 frozen in 4-bit.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import time
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit",
                    help="also try unsloth/Qwen2.5-0.5B-Instruct-bnb-4bit for low-end phones")
    ap.add_argument("--data", default="sentinel/sft")
    ap.add_argument("--out", default="sentinel/outputs")
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max-seq", type=int, default=1024)
    ap.add_argument("--export-gguf", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--grad-accum", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0,
                    help="smoke test: use only the first N train and N val examples (0 = all)")
    ap.add_argument("--max-steps", type=int, default=-1, help="smoke test: stop after this many optimizer steps")
    args = ap.parse_args()
    t_start = time.time()

    from datasets import load_dataset
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastLanguageModel
    from unsloth.chat_templates import train_on_responses_only

    model, tok = FastLanguageModel.from_pretrained(args.base, max_seq_length=args.max_seq, load_in_4bit=True)
    model = FastLanguageModel.get_peft_model(
        model, r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.0,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth", random_state=args.seed,
    )
    ds = load_dataset("json", data_files={"train": f"{args.data}/train.jsonl", "val": f"{args.data}/val.jsonl"})
    if args.limit:
        ds["train"] = ds["train"].select(range(min(args.limit, len(ds["train"]))))
        ds["val"] = ds["val"].select(range(min(args.limit, len(ds["val"]))))
    ds = ds.map(lambda b: {"text": [tok.apply_chat_template(m, tokenize=False) for m in b["messages"]]},
                batched=True, remove_columns=["messages", "meta"])

    # Examples longer than max-seq would lose the assistant JSON (and therefore all their loss) to truncation.
    lengths = [len(tok(t)["input_ids"]) for t in ds["train"]["text"]]
    too_long = sum(n > args.max_seq for n in lengths)
    print(f"train token lengths: max {max(lengths)}, over {args.max_seq}: {too_long}")

    import torch
    bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    cfg = dict(output_dir=args.out, dataset_text_field="text",
               per_device_train_batch_size=args.batch, gradient_accumulation_steps=args.grad_accum,
               num_train_epochs=args.epochs, max_steps=args.max_steps,
               learning_rate=args.lr, lr_scheduler_type="cosine", warmup_ratio=0.03,
               logging_steps=1 if args.limit else 20, eval_strategy="steps", eval_steps=200, save_steps=400,
               fp16=not bf16, bf16=bf16, seed=args.seed, data_seed=args.seed, report_to="none")
    try:                                    # TRL renamed max_seq_length -> max_length
        sft_args = SFTConfig(max_seq_length=args.max_seq, **cfg)
    except TypeError:
        sft_args = SFTConfig(max_length=args.max_seq, **cfg)
    try:                                    # and tokenizer -> processing_class
        trainer = SFTTrainer(model=model, tokenizer=tok, train_dataset=ds["train"], eval_dataset=ds["val"], args=sft_args)
    except TypeError:
        trainer = SFTTrainer(model=model, processing_class=tok, train_dataset=ds["train"], eval_dataset=ds["val"],
                             args=sft_args)
    # Loss only on the assistant's JSON, not on the prompt.
    trainer = train_on_responses_only(trainer, instruction_part="<|im_start|>user\n",
                                      response_part="<|im_start|>assistant\n")
    # Masking check: every example must keep some supervised (answer) tokens and mask the prompt.
    supervised = [sum(1 for v in trainer.train_dataset[i]["labels"] if v != -100)
                  for i in range(min(len(trainer.train_dataset), 200))]
    if min(supervised) == 0:
        raise SystemExit(f"loss mask check FAILED: {supervised.count(0)} of {len(supervised)} examples have no "
                         "supervised tokens (prompt template or truncation problem)")
    print(f"loss mask check ok: supervised tokens per example min {min(supervised)} max {max(supervised)}")
    t_train = time.time()
    result = trainer.train()
    t_done = time.time()
    hist = trainer.state.log_history
    losses = [h["loss"] for h in hist if "loss" in h]
    if not losses or not all(math.isfinite(x) for x in losses):
        raise SystemExit(f"training loss not finite: {losses[-5:]}")
    eval_losses = [h["eval_loss"] for h in hist if "eval_loss" in h]
    final_eval = trainer.evaluate() if args.limit else None
    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    import importlib.metadata as md
    vers = {}
    for pkg in ("torch", "transformers", "trl", "peft", "unsloth", "bitsandbytes", "datasets", "accelerate"):
        try:
            vers[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            vers[pkg] = None
    try:
        from huggingface_hub import HfApi
        base_revision = HfApi().model_info(args.base).sha
    except Exception as e:  # noqa: BLE001 - provenance is best-effort, never blocks training
        base_revision = f"unavailable: {type(e).__name__}"
    Path(args.out).mkdir(parents=True, exist_ok=True)
    log = {"base_model": args.base, "base_model_revision": base_revision,
           "lora": {"rank": args.rank, "alpha": 2 * args.rank, "dropout": 0.0,
                    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]},
           "mode": "smoke" if (args.limit or args.max_steps > 0) else "full",
           "args": vars(args), "effective_batch": args.batch * args.grad_accum,
           "precision": "bf16" if bf16 else "fp16",
           "train_rows": len(ds["train"]), "val_rows": len(ds["val"]),
           "train_tokens_over_max_seq": too_long, "train_token_len_max": max(lengths),
           "global_steps": trainer.state.global_step, "train_runtime_s": round(t_done - t_train, 1),
           "wall_clock_s_including_load": round(t_done - t_start, 1),
           "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_start)),
           "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_done)),
           "final_train_loss": losses[-1], "first_train_loss": losses[0],
           "eval_losses": eval_losses, "smoke_eval": final_eval,
           "train_metrics": result.metrics,
           "hardware": {"gpu": gpu, "gpu_mem_gb": round(torch.cuda.get_device_properties(0).total_memory / 2**30, 1)
                        if gpu else None, "cuda": torch.version.cuda, "python": platform.python_version()},
           "packages": vers, "log_history": hist}
    (Path(args.out) / "training_log.json").write_text(json.dumps(log, indent=2, default=str) + "\n")
    print(f"training done: {trainer.state.global_step} steps in {t_done - t_train:.0f}s; "
          f"loss {losses[0]:.3f} -> {losses[-1]:.3f}")
    model.save_pretrained(f"{args.out}/lora")
    tok.save_pretrained(f"{args.out}/lora")
    if args.export_gguf:
        model.save_pretrained_gguf(f"{args.out}/gguf", tok, quantization_method="q4_k_m")
        print(f"GGUF written to {args.out}/gguf (load it with llama.cpp on Android or WebLLM in the browser)")


if __name__ == "__main__":
    main()
