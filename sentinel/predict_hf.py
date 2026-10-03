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
    a = ap.parse_args()
    import torch
    from unsloth import FastLanguageModel
    model, tok = FastLanguageModel.from_pretrained(a.model, max_seq_length=a.max_seq, load_in_4bit=True)
    FastLanguageModel.for_inference(model)
    tok.padding_side = "left"
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
        for b in range(0, len(rows), a.batch):
            enc = tok([p + PREFIX for p in prompts[b: b + a.batch]], return_tensors="pt", padding=True,
                      truncation=True, max_length=a.max_seq).to(model.device)
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
            for r, res, prompt in zip(rows, results, prompts):
                enc = tok(prompt, return_tensors="pt").to(model.device)
                gen = model.generate(**enc, max_new_tokens=96, do_sample=False)
                raw = tok.decode(gen[0][enc["input_ids"].shape[1]:], skip_special_tokens=True).strip()
                try:
                    res["parsed"] = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
                    res["json_valid"] = True
                except ValueError:
                    res["json_valid"] = False
        with open(out / f.name, "w", encoding="utf-8") as w:
            for res in results:
                w.write(json.dumps(res) + "\n")
        print(f"{f.name}: {len(results)} predictions")


if __name__ == "__main__":
    main()
