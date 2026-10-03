"""Evaluate a Sentinel checkpoint (or any OpenAI-compatible model) on the held-out SFT test split.

    # local fine-tuned model served by llama.cpp:  llama-server -m sentinel/outputs/gguf/*.gguf --port 8080
    python sentinel/evaluate.py --base-url http://localhost:8080/v1 --model sentinel

Reports JSON validity, tactic micro-F1, stage accuracy and scam AUC, so you can show
"our 1.5B on-device model vs a large cloud model" on the same never-seen messages.
"""

from __future__ import annotations

import argparse
import json

import httpx
from sklearn.metrics import f1_score, roc_auc_score

TACTICS = ["authority", "urgency", "fear", "greed", "secrecy", "trust_building", "social_proof", "isolation",
           "payment_request", "credential_request", "remote_access", "link_click", "reciprocity"]


def ask(base: str, model: str, key: str, messages: list[dict]) -> dict | None:
    r = httpx.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {key}"}, timeout=60,
                   json={"model": model, "temperature": 0, "messages": messages[:2]})
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"].strip()
    txt = txt[txt.find("{"): txt.rfind("}") + 1]
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", default="sentinel/sft/test.jsonl")
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-key", default="none")
    ap.add_argument("--limit", type=int, default=400)
    args = ap.parse_args()
    rows = [json.loads(x) for x in open(args.test, encoding="utf-8")][: args.limit]
    valid, y_tac, p_tac, y_stage, p_stage, y_scam, p_scam = 0, [], [], [], [], [], []
    for r in rows:
        gold = json.loads(r["messages"][2]["content"])
        pred = ask(args.base_url, args.model, args.api_key, r["messages"]) or {}
        valid += int(bool(pred))
        y_tac.append([int(t in gold["tactics"]) for t in TACTICS])
        p_tac.append([int(t in pred.get("tactics", [])) for t in TACTICS])
        y_stage.append(gold["stage"])
        p_stage.append(pred.get("stage"))
        y_scam.append(r["meta"]["label"])
        p_scam.append(float(pred.get("p_scam", 0.5)))
    print(json.dumps({
        "n": len(rows),
        "json_valid": round(valid / len(rows), 4),
        "tactic_micro_f1": round(f1_score(y_tac, p_tac, average="micro", zero_division=0), 4),
        "stage_accuracy": round(sum(a == b for a, b in zip(y_stage, p_stage)) / len(rows), 4),
        "scam_auc": round(roc_auc_score(y_scam, p_scam), 4) if len(set(y_scam)) > 1 else None,
    }, indent=2))


if __name__ == "__main__":
    main()
