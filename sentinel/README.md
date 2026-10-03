# Sentinel: the on-device scam-workflow model

Sentinel is a small language model (0.5–1.5B parameters) fine-tuned to read a message plus recent session context and return JSON:

```json
{"tactics": ["authority", "urgency"], "stage": "pressure", "next_stage": "payment_ask",
 "family": "digital_arrest", "p_scam": 0.93}
```

It runs on the phone, so raw messages never leave the device; only this JSON goes to the API as `client_tags`. The server's character n-gram tagger returns the same shape and is the fallback.

## Train it (free Colab T4)

```bash
# 1. Build the fine-tuning set from simulator sessions
python sentinel/build_sft.py --sessions backend/data/sessions.jsonl --out sentinel/sft

# 2. On Colab with a T4 GPU
pip install unsloth trl datasets
python sentinel/finetune.py --base unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit --data sentinel/sft --export-gguf
```

One epoch over 12,000 examples takes about 30–40 minutes on a T4. For low-end phones, use `unsloth/Qwen2.5-0.5B-Instruct-bnb-4bit`.

What the training does:

- **QLoRA:** the base model stays frozen in 4-bit; only low-rank adapters are trained, W = W0 + (alpha / r) BA with r = 16.
- **Loss on the answer only:** the prompt tokens are masked, so the model learns to produce the JSON rather than repeat the input.
- **Soft scam probabilities:** targets rise with the kill-chain stage instead of being 0 or 1, so the model learns calibrated confidence.
- **Honest test split:** the test set uses message wordings and a scam family that never appear in training.

## Evaluate it

Serve the GGUF with llama.cpp and compare it against any OpenAI-compatible model on the same held-out messages:

```bash
llama-server -m sentinel/outputs/gguf/*.gguf --port 8080
python sentinel/evaluate.py --base-url http://localhost:8080/v1 --model sentinel
python sentinel/evaluate.py --base-url https://api.groq.com/openai/v1 --model llama-3.3-70b-versatile --api-key $GROQ_API_KEY
```

It reports JSON validity, tactic F1, stage accuracy and scam AUC.

## On the phone

- **Android:** llama.cpp (or MLC LLM) with the Q4_K_M GGUF, about 1 GB for the 1.5B model.
- **Browser demo:** WebLLM with an MLC build of the same weights.
