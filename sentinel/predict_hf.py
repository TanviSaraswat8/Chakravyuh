"""Run a fine-tuned Sentinel over SFT test files. GPU expected (Colab T4 or better).

    python sentinel/predict_hf.py --model sentinel/outputs/sentinel_real_v2_clean/lora \
        --data sentinel/sft_real/sentinel_real_v2_clean --out sentinel/outputs/sentinel_real_v2_clean/predictions

Per test file, one JSONL row per example:
    {record_id, p_scam, p_label: {scam, promo, legit}, label_pred, parsed, json_valid, latency_ms}

p_scam is the model's probability of the first label token for "scam", renormalised over the three
labels, after the forced prefix '{"label": "' — a single batched forward pass, used for thresholds.
Full JSON generation (scam_type, lures) runs only on files listed in --generate (default: IMC'25 test).
NOTE: written without GPU access or model downloads in the build environment; first run it with
--limit 50 and check the printed label-token ids.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

PREFIX = '{"label": "'
LABELS = ["scam", "promo", "legit"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-seq", type=int, default=384)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--generate", nargs="*", default=["test_imc25_group_v1_test.jsonl"])
    ap.add_argument("--gen-batch", type=int, default=32)
    ap.add_argument("--latency-n", type=int, default=100, help="messages timed one at a time (batch 1)")
    a = ap.parse_args()
    import torch
    from unsloth import FastLanguageModel
    model, tok = FastLanguageModel.from_pretrained(a.model, max_seq_length=a.max_seq, load_in_4bit=True)
    FastLanguageModel.for_inference(model)
    tok.padding_side = "left"
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    first = {lab: tok.encode(lab, add_special_tokens=False)[0] for lab in LABELS}
    print("label first-token ids:", first)
    if len(set(first.values())) != 3:
        raise SystemExit("label first tokens collide; switch to full-sequence scoring")
    ids = torch.tensor(list(first.values()), device=model.device)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for f in sorted(Path(a.data).glob("test_*.jsonl")):
        rows = [json.loads(x) for x in open(f, encoding="utf-8")]
        rows = rows[: a.limit] if a.limit else rows
        prompts = [tok.apply_chat_template(r["messages"][:2], tokenize=False, add_generation_prompt=True) for r in rows]
        results = []
        over_max = 0
        for b in range(0, len(rows), a.batch):
            # No truncation: cutting the prompt would drop the forced prefix. SMS prompts are far below max-seq.
            enc = tok([p + PREFIX for p in prompts[b: b + a.batch]], return_tensors="pt", padding=True).to(model.device)
            over_max += int((enc["attention_mask"].sum(1) > a.max_seq).sum())
            t0 = time.perf_counter()
            with torch.no_grad():
                logits = model(**enc).logits[:, -1, :]
            ms = (time.perf_counter() - t0) * 1000 / enc["input_ids"].shape[0]
            probs = torch.softmax(logits[:, ids].float(), dim=-1).cpu().tolist()
            for r, pr in zip(rows[b: b + a.batch], probs):
                p = dict(zip(LABELS, pr))
                results.append({"record_id": r["meta"]["record_id"], "p_scam": p["scam"], "p_label": p,
                                "label_pred": max(p, key=p.get), "parsed": None, "json_valid": None,
                                "latency_ms": ms})
        if f.name in a.generate:
            for b in range(0, len(rows), a.gen_batch):
                enc = tok(prompts[b: b + a.gen_batch], return_tensors="pt", padding=True).to(model.device)
                with torch.no_grad():
                    gen = model.generate(**enc, max_new_tokens=96, do_sample=False, pad_token_id=tok.pad_token_id)
                for k, res in enumerate(results[b: b + a.gen_batch]):
                    raw = tok.decode(gen[k][enc["input_ids"].shape[1]:], skip_special_tokens=True).strip()
                    res["raw"] = raw
                    try:
                        obj = json.loads(raw)            # strict: the whole output must be one JSON object
                        ok = isinstance(obj, dict) and obj.get("label") in LABELS
                    except ValueError:
                        obj, ok = None, False
                    res["parsed"], res["json_valid"] = obj, ok
            if a.latency_n:
                single = []
                for prompt in prompts[: a.latency_n]:
                    enc = tok(prompt + PREFIX, return_tensors="pt").to(model.device)
                    torch.cuda.synchronize()
                    t0 = time.perf_counter()
                    with torch.no_grad():
                        model(**enc)
                    torch.cuda.synchronize()
                    single.append((time.perf_counter() - t0) * 1000)
                single.sort()
                (out / "latency_single.json").write_text(json.dumps({
                    "n": len(single), "batch": 1, "what": "one forward pass for p_scam (no generation)",
                    "gpu": torch.cuda.get_device_name(0), "p50_ms": single[len(single) // 2],
                    "p95_ms": single[int(len(single) * 0.95) - 1]}, indent=2) + "\n")
        with open(out / f.name, "w", encoding="utf-8") as w:
            for res in results:
                w.write(json.dumps(res) + "\n")
        print(f"{f.name}: {len(results)} predictions; prompts over max-seq: {over_max}")


if __name__ == "__main__":
    main()
