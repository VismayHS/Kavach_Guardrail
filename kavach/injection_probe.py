"""Prompt-injection classifier on what the agent reads (C3), on CPU.

Every piece of untrusted content (an email, a web page, a file, a transaction's subject) is scanned when it enters
the task, before the agent acts on it. A hit marks that source hostile:
  * "reply to sender" trust is withdrawn for that message (provenance),
  * rule R29 sends state-changing actions in that task to a human unless every destination was typed by the user.
It never blocks on its own: a classifier is a model signal, and only deterministic rules may block.

Default model: protectai/deberta-v3-base-prompt-injection-v2 (open, the one AgentDojo uses for its PI-detector
baseline). Meta's Llama-Prompt-Guard-2-22M (smaller, gated on Hugging Face) works too:
KAVACH_PROBE_MODEL=meta-llama/Llama-Prompt-Guard-2-22M. Runs on CPU (about 50 ms per text after warm-up); the
model loads on first use. Needs `pip install torch transformers`; without them the probe reports itself disabled.
"""
from __future__ import annotations

import os
import time
from collections.abc import Callable

DEFAULT_MODEL = "protectai/deberta-v3-base-prompt-injection-v2"
POSITIVE = {"INJECTION", "MALICIOUS", "LABEL_1", "JAILBREAK", "UNSAFE"}
CHUNK = 1800          # characters per window (well under the 512-token limit)
MAX_CHUNKS = 8        # long documents: scan the first 8 windows


class InjectionProbe:
    def __init__(self, model: str | None = None, threshold: float = 0.5, device: str = "cpu",
                 classify: Callable[[str], tuple[str, float]] | None = None):
        """`classify` replaces the model (tests, or another detector): text -> (label, score)."""
        self.model_name = model or os.environ.get("KAVACH_PROBE_MODEL", DEFAULT_MODEL)
        self.threshold, self.device = threshold, device
        self._classify = classify
        self._pipe = None
        self.latency_ms: list[float] = []

    @property
    def enabled(self) -> bool:
        if self._classify is not None:
            return True
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
            return True
        except ImportError:
            return False

    def _model(self, text: str) -> tuple[str, float]:
        if self._classify is not None:
            return self._classify(text)
        if self._pipe is None:
            from transformers import pipeline
            self._pipe = pipeline("text-classification", model=self.model_name, device=self.device, truncation=True,
                                  max_length=512)
        r = self._pipe(text)[0]
        return str(r["label"]), float(r["score"])

    def scan(self, text: str) -> dict:
        """{'injection': bool, 'score': p(injection), 'ms': ...} for one text (long texts in windows, max over them)."""
        t0 = time.perf_counter()
        text = str(text or "")
        best = 0.0
        for i in range(0, min(len(text), CHUNK * MAX_CHUNKS) or 1, CHUNK):
            label, score = self._model(text[i:i + CHUNK])
            p = score if label.upper() in POSITIVE else 1.0 - score
            best = max(best, p)
            if best >= 0.99:
                break
        ms = (time.perf_counter() - t0) * 1000
        self.latency_ms.append(ms)
        return {"injection": best >= self.threshold, "score": round(best, 4), "ms": round(ms, 1),
                "model": "custom" if self._classify else self.model_name}
