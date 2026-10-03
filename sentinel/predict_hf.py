"""Run a fine-tuned Sentinel (LoRA or merged) over SFT test files and write predictions. GPU expected.

    python sentinel/predict_hf.py --model sentinel/outputs/sentinel_real_v1/lora \
        --data sentinel/sft_real/sentinel_real_v1 --out sentinel/outputs/sentinel_real_v1/predictions

One predictions file per test file: {record_id, raw, parsed, json_valid, latency_ms}.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-seq", type=int, default=512)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    from unsloth import FastLanguageModel
    model, tok = FastLanguageModel.from_pretrained(a.model, max_seq_length=a.max_seq, load_in_4bit=True)
    FastLanguageModel.for_inference(model)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for f in sorted(Path(a.data).glob("test_*.jsonl")):
        rows = [json.loads(x) for x in open(f, encoding="utf-8")]
        rows = rows[: a.limit] if a.limit else rows
        with open(out / f.name, "w", encoding="utf-8") as w:
            for r in rows:
                prompt = tok.apply_chat_template(r["messages"][:2], tokenize=False, add_generation_prompt=True)
                ids = tok(prompt, return_tensors="pt").to(model.device)
                t0 = time.perf_counter()
                gen = model.generate(**ids, max_new_tokens=96, do_sample=False)
                ms = (time.perf_counter() - t0) * 1000
                raw = tok.decode(gen[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()
                try:
                    parsed = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
                except ValueError:
                    parsed = None
                w.write(json.dumps({"record_id": r["meta"]["record_id"], "raw": raw, "parsed": parsed,
                                    "json_valid": parsed is not None, "latency_ms": ms}) + "\n")
        print(f"{f.name}: {len(rows)} predictions")


if __name__ == "__main__":
    main()
