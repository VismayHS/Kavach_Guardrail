"""Provenance / taint tracking by value lineage.

Every value the agent could later put into a tool argument is registered with a
label when it first enters the task: the user's request (trusted), or a tool
output (labelled by the tool manifest: e.g. inbox and web content is untrusted,
CRM rows are PII). When a tool call arrives, each argument is matched back to the
values it was built from.

This is an approximation of information-flow control (exact IFC needs the agent
to run inside an interpreter, as in CaMeL / FIDES). Value lineage needs no change
to the agent, which is what makes the gateway drop-in. Its known blind spot
(paraphrased or re-encoded values) is covered by fail-safe defaults: a control
argument that matches nothing the user typed is never labelled "trusted".
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .models import Conf, Label, Trust

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL = re.compile(r"https?://[^\s\"'<>)]+")
ACCOUNT = re.compile(r"\bACC-\d{2}-\d{4}\b")
PHONE = re.compile(r"\+91-9\d{9}")
NUMBER = re.compile(r"(?<![\w.-])\d[\d,]*(?:\.\d+)?(?![\w-])")


def _norm_num(s: str) -> str:
    try:
        v = float(s.replace(",", ""))
        return str(int(v)) if v == int(v) else str(v)
    except ValueError:
        return s


def entities(text: str) -> set[str]:
    out: set[str] = set()
    out |= {e.lower() for e in EMAIL.findall(text)}
    out |= {u.rstrip(".,") for u in URL.findall(text)}
    out |= set(ACCOUNT.findall(text))
    out |= set(PHONE.findall(text))
    out |= {"#" + _norm_num(n) for n in NUMBER.findall(text) if len(n.replace(",", "")) >= 3}
    return out


def shingles(text: str, k: int = 6) -> set[str]:
    words = re.findall(r"[a-z0-9@._-]+", text.lower())
    return {" ".join(words[i:i + k]) for i in range(max(0, len(words) - k + 1))}


@dataclass
class ProvenanceTracker:
    user_entities: set[str] = field(default_factory=set)
    origins: dict[str, list[Label]] = field(default_factory=dict)
    untrusted_shingles: dict[str, str] = field(default_factory=dict)   # shingle -> source
    pii_values: set[str] = field(default_factory=set)
    user_text: str = ""

    def register_user(self, text: str) -> None:
        self.user_text += " " + text
        self.user_entities |= entities(text)

    def register_output(self, tool: str, output, trust: str, conf: Conf) -> None:
        records = output if isinstance(output, list) else [output]
        for rec in records:
            src = f"tool:{tool}"
            if isinstance(rec, dict) and "id" in rec:
                src += f"#{rec['id']}"
            text = rec if isinstance(rec, str) else json.dumps(rec, default=str)
            t = Trust(trust) if trust in ("untrusted", "derived", "trusted") else Trust.DERIVED
            lab = Label(t, conf, [src])
            for e in entities(text):
                is_pii = e.startswith("+91") or "@" in e
                e_conf = conf if (conf != Conf.PII or is_pii) else Conf.CONFIDENTIAL
                self.origins.setdefault(e, []).append(Label(t, e_conf, [src]))
                if conf == Conf.PII and is_pii:
                    self.pii_values.add(e)
            if lab.trust == Trust.UNTRUSTED:
                for sh in shingles(text):
                    self.untrusted_shingles.setdefault(sh, src)

    def label(self, value, is_control: bool) -> Label:
        text = value if isinstance(value, str) else str(value)
        ents = entities(text) if isinstance(value, str) else {"#" + _norm_num(text)}
        pii = sum(1 for e in ents if e in self.pii_values)
        conf = Conf.PII if pii else Conf.INTERNAL
        sources: list[str] = []
        trust = Trust.DERIVED

        # 1) verbatim copy of untrusted text (e.g. an injected SQL statement or instruction)
        copied = {self.untrusted_shingles[s] for s in shingles(text) if s in self.untrusted_shingles}
        if copied:
            trust, sources = Trust.UNTRUSTED, sorted(copied)

        # 2) entity lineage: where did each address / account / amount come from?
        for e in ents:
            if e in self.user_entities:
                if trust != Trust.UNTRUSTED or not is_control:
                    sources.append("user")
                continue
            for lab in self.origins.get(e, []):
                sources.extend(lab.sources)
                if lab.trust == Trust.UNTRUSTED:
                    trust = Trust.UNTRUSTED
                if lab.conf.rank > conf.rank:
                    conf = lab.conf

        if is_control and ents and all(e in self.user_entities for e in ents) and not copied:
            trust = Trust.TRUSTED
        if not sources:
            sources = ["agent"]
        return Label(trust, conf, sorted(set(sources)), pii)
