from __future__ import annotations

"""
llm.py — Minimal OpenAI-compatible chat client
================================================
Used by the Apply Assistant to draft cover letters and talking points.

Provider-agnostic on purpose: OpenRouter, Groq, Mistral and most others expose
the same ``POST /chat/completions`` shape, so switching providers is a config
change (base_url + model + api_key_env), not a code change. Defaults to a free
OpenRouter model.
"""

import json
import os
from typing import Optional

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


# Sensible defaults — overridable via the `llm:` block in config.yaml.
_DEFAULTS = {
    "base_url": "https://openrouter.ai/api/v1",
    "model": "meta-llama/llama-3.3-70b-instruct:free",
    "api_key_env": "OPENROUTER_API_KEY",
    "temperature": 0.4,
    "max_tokens": 1200,
    "timeout": 45.0,
}


class LLMClient:
    """Thin wrapper over an OpenAI-compatible chat completions endpoint."""

    def __init__(self, config: dict) -> None:
        cfg = {**_DEFAULTS, **(config.get("llm", {}) or {})}
        self.base_url = str(cfg["base_url"]).rstrip("/")
        self.model = cfg["model"]
        self.temperature = float(cfg["temperature"])
        self.max_tokens = int(cfg["max_tokens"])
        self.timeout = float(cfg["timeout"])
        self.api_key = os.environ.get(str(cfg["api_key_env"]), "")

    @property
    def available(self) -> bool:
        return HTTPX_AVAILABLE and bool(self.api_key)

    def chat(
        self,
        system: str,
        user: str,
        json_mode: bool = False,
    ) -> Optional[str]:
        """Send a single-turn chat request. Returns the assistant text or None."""
        if not self.available:
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # OpenRouter uses these for attribution; harmless for other providers.
            "HTTP-Referer": "https://github.com/DewanggaDew/job-scraper",
            "X-Title": "Job Scraper Apply Assistant",
        }
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                print(f"  [LLM] ⚠️ {self.model} returned {resp.status_code}: {resp.text[:300]}")
                return None
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            print(f"  [LLM] ⚠️ request failed: {exc}")
            return None

    def chat_json(self, system: str, user: str) -> Optional[dict]:
        """Like chat(), but parse the response as JSON. Returns None on failure."""
        raw = self.chat(system, user, json_mode=True)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Some free models wrap JSON in markdown fences or prose — salvage it.
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(raw[start : end + 1])
                except json.JSONDecodeError:
                    pass
            print("  [LLM] ⚠️ could not parse JSON response.")
            return None
