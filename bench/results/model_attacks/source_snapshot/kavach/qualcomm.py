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
import random
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


def sequential_tool_calls(messages: list[dict]) -> list[dict]:
    """The Inference Cloud answers 500 "Model Config not found" to any request holding two tool results in a row
    (measured 2 Nov 2026), i.e. after the model made parallel tool calls. Re-send such a turn as one (assistant call,
    tool result) pair per call; the model sees the same calls and results, in order."""
    out, used = [], set()
    for i, m in enumerate(messages):
        if m.get("role") == "tool" and m.get("tool_call_id") in used:
            continue
        calls = m.get("tool_calls") or []
        if m.get("role") != "assistant" or len(calls) < 2:
            out.append(m)
            continue
        results = {r.get("tool_call_id"): r for r in messages[i + 1:] if r.get("role") == "tool"}
        if not all(c.get("id") in results for c in calls):
            out.append(m)                       # unpaired: leave it as it was
            continue
        for j, c in enumerate(calls):
            out.append({**m, "content": m.get("content") if j == 0 else "", "tool_calls": [c]})
            out.append(results[c["id"]])
            used.add(c["id"])
    return out


ANSWER_TOOL = {"type": "function", "function": {
    "name": "answer", "description": "Give your answer: the JSON object you were asked for, as this function's arguments.",
    "parameters": {"type": "object", "properties": {}, "additionalProperties": True}}}
ANSWER_CHOICE = {"type": "function", "function": {"name": "answer"}}


class QualcommCloudAI:
    def __init__(self, endpoint: str | None = None, api_key: str | None = None,
                 model: str | None = None, timeout: float = 8.0, max_wait_s: float = 4.0, component: str = "model"):
        """max_wait_s: how long, in total, to wait out rate limits (429), server errors and timeouts before giving
        up. Small for the judge and the explainer (they sit on the decision path and can only add strictness, so
        giving up is safe); long for an agent, which should wait as long as the service asks rather than fail.
        component: who is calling (judge, explainer, planner, agent...), for the usage and cost metrics."""
        self.component = component
        self.max_wait_s = max_wait_s
        self.rate_limited = 0
        self.retries = 0
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
        """POST with retries: a 429 waits as long as the service asks ("Please wait 19.00 seconds" or Retry-After),
        5xx and network errors back off exponentially, all with jitter, within max_wait_s in total."""
        deadline, attempt = time.monotonic() + self.max_wait_s, 0
        while True:
            t0 = time.perf_counter()
            try:
                # connecting gets its own short limit: the service sometimes hangs at connect, and a fresh
                # connection is cheap, while the full timeout is for the model writing a long answer
                r = httpx.post(f"{self.endpoint}/{path}", json=body,
                               timeout=httpx.Timeout(self.timeout, connect=min(10.0, self.timeout)),
                               headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                                        "User-Agent": "kavach-guardrail/0.1"})
            except (httpx.ConnectTimeout, httpx.ConnectError) as e:
                err, wait = e, 0.5                           # never connected: try again almost at once
            except (httpx.TimeoutException, httpx.TransportError) as e:
                err, wait = e, min(30.0, 2.0 ** attempt)
            else:
                if r.status_code < 400:
                    self.last_latency_ms = round((time.perf_counter() - t0) * 1000, 1)
                    return r.json()
                # keep the service's own message: "500" alone hid the cause once
                err = httpx.HTTPStatusError(f"{r.status_code} from {path}: {r.text[:300]}", request=r.request,
                                            response=r)
                if r.status_code != 429 and r.status_code < 500:
                    raise err
                wait = min(30.0, 2.0 ** attempt)
                if r.status_code == 429:
                    self.rate_limited += 1
                    asked = re.search(r"wait ([\d.]+) seconds", r.text or "")
                    hdr = r.headers.get("retry-after", "")
                    wait = max(wait, float(asked.group(1)) + 1.0 if asked else
                               float(hdr) if hdr.replace(".", "", 1).isdigit() else 0.0)
            attempt += 1
            wait += random.uniform(0, 1.5)
            if time.monotonic() + wait > deadline:
                raise err
            self.retries += 1
            time.sleep(wait)

    def chat(self, messages: list[dict], max_tokens: int = 256, temperature: float = 0.0,
             tools: list[dict] | None = None, model: str | None = None, tool_choice=None) -> dict:
        body = {"model": model or self.model, "messages": sequential_tool_calls(messages), "max_tokens": max_tokens,
                "temperature": temperature, "stream": False}
        if tools:
            body["tools"] = tools
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
        from .usage import METER                   # every call is counted: tokens from the reply's own usage field
        before = self.retries
        try:
            out = self._post("chat/completions", body)
        except Exception:
            METER.record(self.component, body["model"], None, ok=False, retries=self.retries - before)
            raise
        METER.record(self.component, body["model"], out.get("usage") if isinstance(out, dict) else None, ok=True,
                     retries=self.retries - before)
        return out

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
        """A JSON object from the model. Qualcomm's endpoint reads a reply that starts with "{" as a tool call and
        drops it (Llama-3.3-70B, 3 Nov 2026: content "", one nameless call with arguments "{}"), so the JSON comes
        back as the arguments of a forced 'answer' tool. A server that answers in text anyway is read from the text;
        one that rejects tools is asked again without them."""
        try:
            msg = self.chat(messages, tools=[ANSWER_TOOL], tool_choice=ANSWER_CHOICE, **kw)["choices"][0]["message"]
        except httpx.HTTPStatusError:
            msg = self.chat(messages, **kw)["choices"][0]["message"]
        for c in msg.get("tool_calls") or []:
            args = (c.get("function") or {}).get("arguments")
            if isinstance(args, dict) and args:
                return args
            if isinstance(args, str) and args.strip() not in ("", "{}"):
                return json.loads(args)
        text = msg.get("content") or ""
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("no JSON in the model's reply (empty, or swallowed by the endpoint's tool-call parser)")
        return json.loads(text[start:end + 1])
