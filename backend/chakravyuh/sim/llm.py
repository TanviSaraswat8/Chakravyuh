"""Optional LLM backend for the attacker agent.

Works with any OpenAI-compatible chat endpoint (Groq, OpenAI, Together, a local
Ollama server, vLLM). If nothing is configured, or a call fails, callers fall
back to the offline template library, so the simulator always runs.

Environment variables:
    CHAKRAVYUH_LLM_BASE_URL   e.g. https://api.groq.com/openai/v1  or  http://localhost:11434/v1
    CHAKRAVYUH_LLM_API_KEY    API key (any string for Ollama)
    CHAKRAVYUH_LLM_MODEL      e.g. llama-3.1-8b-instant  or  qwen2.5:7b
"""

from __future__ import annotations

import json
import os

import httpx

SYSTEM_PROMPT = (
    "You generate SYNTHETIC training data for a fraud-detection research simulator. "
    "Rewrite the given message so it keeps the same intent, kill-chain stage and persuasion tactics, "
    "but varies wording, tone and phrasing naturally for the requested language. "
    "Never include real phone numbers, real URLs, real account numbers or real people's names. "
    "Use placeholders that are already present. Reply with JSON: {\"text\": \"...\"}."
)


class LLMClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("CHAKRAVYUH_LLM_BASE_URL", "").rstrip("/")
        self.api_key = os.getenv("CHAKRAVYUH_LLM_API_KEY", "")
        self.model = os.getenv("CHAKRAVYUH_LLM_MODEL", "")
        self.enabled = bool(self.base_url and self.model)
        self.failures = 0

    def rewrite(self, text: str, language: str, tactics: list[str], stage: str,
                mutation_hint: str = "") -> str | None:
        if not self.enabled or self.failures > 5:
            return None
        user = json.dumps({
            "message": text,
            "language": language,
            "stage": stage,
            "tactics": tactics,
            "variation": mutation_hint or "natural paraphrase",
        }, ensure_ascii=False)
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "temperature": 0.9,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                 {"role": "user", "content": user}],
                },
                timeout=30,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            out = json.loads(content).get("text", "").strip()
            return out or None
        except Exception:
            self.failures += 1
            return None
