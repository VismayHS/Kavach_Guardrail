"""Explanations (stage 8): written from the evidence, never the other way round.

The template explanation is always produced. If Qualcomm Cloud AI is configured,
an LLM rewrites it in plain English, and the rewrite is accepted only if every
number it contains also appears in the evidence (a cheap faithfulness check) and,
for a blocked or escalated action, it doesn't call the action safe or approved;
otherwise the template is used. The explanation can never change the verdict.
"""
from __future__ import annotations

import json
import re

from .qualcomm import QualcommCloudAI

NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Words a rewrite of a blocked or escalated action may not use unless negated: "safe and approved" on a DENY.
CONTRADICTS = re.compile(r"(?<!not )(?<!n't )(?<!never )\b(safe|approved|allowed|harmless|no risk|go ahead)\b", re.I)


LABELS = {
    "en": {"Why": "Why", "Impact": "Impact", "Reversibility": "Reversibility", "safeguard": "safeguard available",
           "Risk": "Risk", "threshold": "vs threshold", "intent": "intent", "Instead": "Instead",
           "ALLOW": "ALLOW", "ALLOW_WITH_SAFEGUARD": "ALLOW_WITH_SAFEGUARD", "ESCALATE": "ESCALATE", "DENY": "DENY"},
    # Hindi (F8): the frame is translated; rule messages are generated text and stay in English unless the
    # faithfulness-checked LLM rewrite is on
    "hi": {"Why": "कारण", "Impact": "प्रभाव", "Reversibility": "क्या इसे वापस लिया जा सकता है",
           "safeguard": "सुरक्षा उपाय", "Risk": "जोखिम", "threshold": "सीमा", "intent": "इरादा",
           "Instead": "इसके बजाय", "ALLOW": "अनुमति है", "ALLOW_WITH_SAFEGUARD": "अनुमति है (वापस लिया जा सकता है)",
           "ESCALATE": "किसी व्यक्ति की स्वीकृति चाहिए", "DENY": "रोका गया"},
}
LANGUAGE_NAMES = {"en": "English", "hi": "Hindi"}


def template(d: dict, lang: str = "en") -> str:
    L = LABELS.get(lang, LABELS["en"])
    v, call = d["verdict"], d["call"]
    lines = [f"{L.get(v, v)}: {call['tool']}({', '.join(f'{k}={str(x)[:40]!r}' for k, x in call['args'].items())})"]
    hard = [g for g in d["gates"] if g["outcome"] != "PASS"]
    if hard:
        lines.append(f"{L['Why']}: " + " ".join(f"[{g['rule_id']}] {g['message']}" for g in hard[:3]))
    if d.get("effect"):
        lines.append(f"{L['Impact']} ({d['effect']['method']}): {d['effect']['summary']}")
        lines.append(f"{L['Reversibility']}: {d['effect']['reversibility']}"
                     + (f"; {L['safeguard']}: {d['effect']['safeguard']}" if d['effect'].get('safeguard') else ""))
    if d.get("risk"):
        r = d["risk"]
        lines.append(f"{L['Risk']}: p(harm)={r['p_harm']:.2f} [{r['p_lo']:.2f}-{r['p_hi']:.2f}] {L['threshold']} "
                     f"tau={r['tau']:.3f}; {L['intent']}: {r['intent'].get('reason', '')}")
    if d.get("replan_hint"):
        lines.append(f"{L['Instead']}: " + d["replan_hint"])
    return "\n".join(lines)


class Explainer:
    def __init__(self, llm: QualcommCloudAI | None = None, use_llm: bool = False):
        self.llm = llm or QualcommCloudAI()
        self.use_llm = use_llm

    def explain(self, d: dict, lang: str = "en") -> tuple[str, str]:
        base = template(d, lang)
        if not (self.use_llm and self.llm.enabled):
            return base, "template"
        evidence = json.dumps({k: d[k] for k in ("verdict", "call", "gates", "effect", "risk", "replan_hint")},
                              default=str)
        try:
            text = self.llm.chat_text([
                {"role": "system", "content": "Rewrite this guardrail decision for a non-technical approver in at "
                 f"most 3 sentences, in {LANGUAGE_NAMES.get(lang, 'English')}. Use only facts present in the evidence. "
                 "Do not add numbers."},
                {"role": "user", "content": base + "\n\nEVIDENCE:\n" + evidence[:6000]}], max_tokens=160)
            allowed = {n.replace(",", "") for n in NUM.findall(evidence + base)}
            if d["verdict"] in ("DENY", "ESCALATE") and CONTRADICTS.search(text):
                return base, "template (llm rewrite rejected: contradicts the verdict)"
            if all(n.replace(",", "") in allowed for n in NUM.findall(text)):
                return text.strip() + "\n\n" + base, "qualcomm-llm (faithfulness-checked)"
            return base, "template (llm rewrite rejected: unfaithful number)"
        except Exception:
            return base, "template (llm unavailable)"
