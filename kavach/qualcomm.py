"""Qualcomm Cloud AI (AI Inference Suite / Imagine API) client.

Mirrors python-imagine-sdk 0.5.0 (PyPI, read from the wheel source):
  * auth header   Authorization: Bearer <IMAGINE_API_KEY>
  * base URL      IMAGINE_API_ENDPOINT   (Cirrascale playground: https://aisuite.cirrascale.com/apis/v2)
  * routes        POST chat/completions (OpenAI wire format, supports `tools`), POST embeddings,
                  POST reranker, GET models, GET health
  * SDK defaults  LLM "Llama-3.1-8B", embeddings "BAAI/bge-large-en-v1.5", reranker "BAAI/bge-reranker-base"
Check GET models with your key: the live model list on the playground may differ.
Env names: IMAGINE_API_KEY or INFERENCE_CLOUD_API_KEY; IMAGINE_API_ENDPOINT, IMAGINE_ENDPOINT_URL (Qualcomm's SDK docs)
or INFERENCE_CLOUD_ENDPOINT (Cirrascale's Inference Cloud).

Measured on the Inference Cloud, 2 Nov 2026: models Llama-3.1-8B, Llama-3.3-70B, DeepSeek-R1-Distill-Llama-70B,
Qwen-QwQ-32B. Both Llamas answer and call tools (booleans arrive as strings, e.g. "true"); Qwen-QwQ-32B returned
500 "Parsing Failure"; DeepSeek-R1 thinks out loud (<think>) and took 19 s to say OK. JSON answers come back as an
empty tool call, so KAVACH's judge asks for plain text. A request without a key gets 500, not 401.

Used by KAVACH for: (1) the reasoning-blind intent judge, (2) explanations written
only from the evidence JSON, (3) the protected agent's own model in the live demo.
Every call has a timeout and a deterministic fallback, so a network failure can
never turn into an ALLOW.
"""
from __future__ import annotations

import json
import os
import re
import time

try:
    import httpx
except ImportError:  # optional dependency
    httpx = None


# "Thinking" models write their reasoning before the answer: too slow and too long for a yes/no judge
REASONING = re.compile(r"(?<![A-Za-z0-9])R1(?![0-9])|QwQ|reason|think", re.I)


def _env(*names: str) -> str:
    return next((os.environ[n] for n in names if os.environ.get(n)), "")


class QualcommCloudAI:
    def __init__(self, endpoint: str | None = None, api_key: str | None = None,
                 model: str | None = None, timeout: float = 8.0):
        self.endpoint = (endpoint or _env("IMAGINE_API_ENDPOINT", "IMAGINE_ENDPOINT_URL", "INFERENCE_CLOUD_ENDPOINT")
                         ).rstrip("/")
        self.api_key = api_key or _env("IMAGINE_API_KEY", "INFERENCE_CLOUD_API_KEY")
        self.model = model or os.environ.get("KAVACH_JUDGE_MODEL", "Llama-3.1-8B")
        self.timeout = timeout
        self.last_latency_ms: float | None = None
        self.picked: tuple[str, str] | None = None     # (fast, strong) judge models, once read from GET /models

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

    def pick_models(self) -> tuple[str, str]:
        """(fast, strong) chat models for the two-stage judge: the smallest and largest by size in the name ("8B",
        "70B") in the live GET /models list, leaving out thinking models (DeepSeek-R1, QwQ). KAVACH_JUDGE_MODEL / KAVACH_JUDGE_STRONG_MODEL override; if the list
        can't be read, both stages use the configured model (and the list is asked for again next time)."""
        if self.picked is None:
            try:
                d = self.models()
                names = list(d.get("llm") or []) + [m.get("id", "") for m in d.get("data") or [] if isinstance(m, dict)]
                names = [n for n in names if not REASONING.search(n)]
            except Exception:
                names = []
            sized = sorted((float(m.group(1)), n) for n in names if (m := re.search(r"(\d+(?:\.\d+)?)B\b", n, re.I)))
            if not sized:
                return self.model, os.environ.get("KAVACH_JUDGE_STRONG_MODEL", self.model)
            self.picked = (os.environ.get("KAVACH_JUDGE_MODEL", sized[0][1]),
                           os.environ.get("KAVACH_JUDGE_STRONG_MODEL", sized[-1][1]))
        return self.picked

    def chat_json(self, messages: list[dict], **kw) -> dict:
        text = self.chat_text(messages, **kw)
        start, end = text.find("{"), text.rfind("}")
        return json.loads(text[start:end + 1])
