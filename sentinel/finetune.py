"""QLoRA fine-tune of the Sentinel SLM. Designed for a free Colab T4 GPU.

    pip install unsloth trl datasets
    python sentinel/finetune.py --base unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit --data sentinel/sft --out sentinel/outputs

Then export for the phone (llama.cpp GGUF, 4-bit) with --export-gguf.
The LoRA update: W = W0 + (alpha / r) * B A, with W0 frozen in 4-bit.
"""

from __future__ import annotations

import argparse


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
    args = ap.parse_args()

    from datasets import load_dataset
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastLanguageModel
    from unsloth.chat_templates import train_on_responses_only

    model, tok = FastLanguageModel.from_pretrained(args.base, max_seq_length=args.max_seq, load_in_4bit=True)
    model = FastLanguageModel.get_peft_model(
        model, r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.0,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth", random_state=0,
    )
    ds = load_dataset("json", data_files={"train": f"{args.data}/train.jsonl", "val": f"{args.data}/val.jsonl"})
    ds = ds.map(lambda b: {"text": [tok.apply_chat_template(m, tokenize=False) for m in b["messages"]]},
                batched=True, remove_columns=["messages", "meta"])

    trainer = SFTTrainer(
        model=model, tokenizer=tok, train_dataset=ds["train"], eval_dataset=ds["val"],
        args=SFTConfig(
            output_dir=args.out, dataset_text_field="text", max_seq_length=args.max_seq,
            per_device_train_batch_size=8, gradient_accumulation_steps=2, num_train_epochs=args.epochs,
            learning_rate=args.lr, lr_scheduler_type="cosine", warmup_ratio=0.03, logging_steps=20,
            eval_strategy="steps", eval_steps=200, save_steps=400, fp16=True, seed=0, report_to="none",
        ),
    )
    # Loss only on the assistant's JSON, not on the prompt.
    trainer = train_on_responses_only(trainer, instruction_part="<|im_start|>user\n",
                                      response_part="<|im_start|>assistant\n")
    trainer.train()
    model.save_pretrained(f"{args.out}/lora")
    tok.save_pretrained(f"{args.out}/lora")
    if args.export_gguf:
        model.save_pretrained_gguf(f"{args.out}/gguf", tok, quantization_method="q4_k_m")
        print(f"GGUF written to {args.out}/gguf (load it with llama.cpp on Android or WebLLM in the browser)")


if __name__ == "__main__":
    main()
