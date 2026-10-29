"""Qualcomm Cloud AI (AI Inference Suite / Imagine API) client.

Mirrors python-imagine-sdk 0.5.0 (PyPI, read from the wheel source):
  * auth header   Authorization: Bearer <IMAGINE_API_KEY>
  * base URL      IMAGINE_API_ENDPOINT   (Cirrascale playground: https://aisuite.cirrascale.com/apis/v2)
  * routes        POST chat/completions (OpenAI wire format, supports `tools`), POST embeddings,
                  POST reranker, GET models, GET health
  * SDK defaults  LLM "Llama-3.1-8B", embeddings "BAAI/bge-large-en-v1.5", reranker "BAAI/bge-reranker-base"
Check GET models with your key: the live model list on the playground may differ.

Used by KAVACH for: (1) the reasoning-blind intent judge, (2) explanations written
only from the evidence JSON, (3) the protected agent's own model in the live demo.
Every call has a timeout and a deterministic fallback, so a network failure can
never turn into an ALLOW.
"""
from __future__ import annotations

import json
import os
import time

try:
    import httpx
except ImportError:  # optional dependency
    httpx = None


class QualcommCloudAI:
    def __init__(self, endpoint: str | None = None, api_key: str | None = None,
                 model: str | None = None, timeout: float = 8.0):
        self.endpoint = (endpoint or os.environ.get("IMAGINE_API_ENDPOINT", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("IMAGINE_API_KEY", "")
        self.model = model or os.environ.get("KAVACH_JUDGE_MODEL", "Llama-3.1-8B")
        self.timeout = timeout
        self.last_latency_ms: float | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint and self.api_key and httpx is not None)

    def _post(self, path: str, body: dict) -> dict:
        t0 = time.perf_counter()
        r = httpx.post(f"{self.endpoint}/{path}", json=body, timeout=self.timeout,
                       headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                                "User-Agent": "kavach-guardrail/0.1"})
        r.raise_for_status()
        self.last_latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return r.json()

    def chat(self, messages: list[dict], max_tokens: int = 256, temperature: float = 0.0,
             tools: list[dict] | None = None, model: str | None = None) -> dict:
        body = {"model": model or self.model, "messages": messages, "max_tokens": max_tokens,
                "temperature": temperature, "stream": False}
        if tools:
            body["tools"] = tools
        return self._post("chat/completions", body)

    def chat_text(self, messages: list[dict], **kw) -> str:
        return self.chat(messages, **kw)["choices"][0]["message"].get("content") or ""

    def models(self) -> dict:
        r = httpx.get(f"{self.endpoint}/models", timeout=self.timeout,
                      headers={"Authorization": f"Bearer {self.api_key}"})
        r.raise_for_status()
        return r.json()

    def chat_json(self, messages: list[dict], **kw) -> dict:
        text = self.chat_text(messages, **kw)
        start, end = text.find("{"), text.rfind("}")
        return json.loads(text[start:end + 1])
