"""Explanations (stage 8): written from the evidence, never the other way round.

The template explanation is always produced. If Qualcomm Cloud AI is configured,
an LLM rewrites it in plain English, and the rewrite is accepted only if every
number it contains also appears in the evidence (a cheap faithfulness check);
otherwise the template is used. The explanation can never change the verdict.
"""
from __future__ import annotations

import json
import re

from .qualcomm import QualcommCloudAI

NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def template(d: dict) -> str:
    v, call = d["verdict"], d["call"]
    lines = [f"{v}: {call['tool']}({', '.join(f'{k}={str(x)[:40]!r}' for k, x in call['args'].items())})"]
    hard = [g for g in d["gates"] if g["outcome"] != "PASS"]
    if hard:
        lines.append("Why: " + " ".join(f"[{g['rule_id']}] {g['message']}" for g in hard[:3]))
    if d.get("effect"):
        lines.append(f"Impact ({d['effect']['method']}): {d['effect']['summary']}")
        lines.append(f"Reversibility: {d['effect']['reversibility']}"
                     + (f"; safeguard available: {d['effect']['safeguard']}" if d['effect'].get('safeguard') else ""))
    if d.get("risk"):
        r = d["risk"]
        lines.append(f"Risk: p(harm)={r['p_harm']:.2f} [{r['p_lo']:.2f}-{r['p_hi']:.2f}] vs threshold "
                     f"tau={r['tau']:.3f}; intent: {r['intent'].get('reason', '')}")
    if d.get("replan_hint"):
        lines.append("Instead: " + d["replan_hint"])
    return "\n".join(lines)


class Explainer:
    def __init__(self, llm: QualcommCloudAI | None = None, use_llm: bool = False):
        self.llm = llm or QualcommCloudAI()
        self.use_llm = use_llm

    def explain(self, d: dict) -> tuple[str, str]:
        base = template(d)
        if not (self.use_llm and self.llm.enabled):
            return base, "template"
        evidence = json.dumps({k: d[k] for k in ("verdict", "call", "gates", "effect", "risk", "replan_hint")},
                              default=str)
        try:
            text = self.llm.chat_text([
                {"role": "system", "content": "Rewrite this guardrail decision for a non-technical approver in at "
                 "most 3 sentences. Use only facts present in the evidence. Do not add numbers."},
                {"role": "user", "content": base + "\n\nEVIDENCE:\n" + evidence[:6000]}], max_tokens=160)
            allowed = {n.replace(",", "") for n in NUM.findall(evidence + base)}
            if all(n.replace(",", "") in allowed for n in NUM.findall(text)):
                return text.strip() + "\n\n" + base, "qualcomm-llm (faithfulness-checked)"
            return base, "template (llm rewrite rejected: unfaithful number)"
        except Exception:
            return base, "template (llm unavailable)"
