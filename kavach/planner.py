"""Planner mode (E9): exact information flow, after CaMeL (Debenedetti et al., 2025) and FIDES (Costa et al., 2025).

In KAVACH's default mode an agent proposes calls one at a time and KAVACH *infers* where each argument came from, by
matching its value against everything the task has read (provenance.py). That catches copied and lightly disguised
values, but not a value an LLM *composes* from untrusted text ("his handle is mallory, the company is evil.io" becomes
mallory@evil.io, a string that appears nowhere).

In planner mode the flow is known, not inferred:

1. A planner writes the whole plan from the user's request alone. It never sees a tool's output, so nothing an
   email or a web page says can add a step or change a destination.
2. Tool outputs reach later arguments only by reference: "$s1" (a whole output), "$s1.0.from" (a field), or a
   template "Invoice {$s2.id} is paid". Each reference carries the exact label of what it points at: a field the
   manifest marks as someone else's free text (untrusted_fields), or any output of an untrusted tool, is UNTRUSTED.
3. When the plan needs a value *out of* untrusted text, it asks a quarantined extractor: {"extract": {"from": "$s1",
   "type": "email", "question": "..."}}. The extractor (regexes by type, or a model with no tools) returns one typed
   value, and that value keeps the label of its source: an address pulled out of an email is still untrusted.
4. Literals the planner wrote are TRUSTED only if the user typed them; otherwise they are the agent's own (DERIVED).
   A referenced value the user named (or the sender of a message the user asked to reply to) is TRUSTED too.

Every step still goes through KAVACH's full check (rules, consequence staging, risk, approvals, receipts); planner
mode only replaces the inferred labels with exact ones. A step that is refused or waits for a person stops the plan.

    POST /api/v1/plan/run   {"user_request": "...", "plan": [...]}   # or without "plan": the Qualcomm planner writes it
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .models import Conf, Label, ToolCall, Trust, Verdict

REF = re.compile(r"^\$([A-Za-z_]\w*)((?:\.[\w-]+)*)$")
TEMPLATE = re.compile(r"\{\$([A-Za-z_]\w*)((?:\.[\w-]+)*)\}")
EXTRACTORS = {
    "email": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    "url": re.compile(r"https?://[^\s'\"<>]+"),
    "number": re.compile(r"-?\d[\d,]*(?:\.\d+)?"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),
    "account": re.compile(r"\bACC-\d{2}-\d{4}\b"),
    "invoice": re.compile(r"\b(?:INV-?)?\d{3,6}\b"),
}
RANK = {Trust.TRUSTED: 0, Trust.DERIVED: 1, Trust.UNTRUSTED: 2}


class PlanError(ValueError):
    pass


@dataclass
class Out:
    """A step's output and where it came from."""
    value: object
    trust: Trust
    conf: Conf
    source: str
    fields: tuple = ()          # fields of each record that are someone else's free text (untrusted)


def worst(labels: list[Label]) -> Label:
    if not labels:
        return Label(Trust.DERIVED, Conf.PUBLIC, ["agent"])
    t = max((l.trust for l in labels), key=RANK.get)
    c = max((l.conf for l in labels), key=lambda x: x.rank)
    return Label(t, c, sorted({s for l in labels for s in l.sources}), sum(l.pii_entities for l in labels))


def _walk(value, path: list[str]):
    for p in path:
        if isinstance(value, list):
            value = value[int(p)]
        elif isinstance(value, dict):
            value = value[p]
        else:
            raise PlanError(f"can't take .{p} of {type(value).__name__}")
    return value


class PlanRunner:
    def __init__(self, gw, extractor=None):
        """extractor(text, type, question) -> str | None: the quarantined extractor (no tools, sees one value).
        Default: deterministic regexes by type; pass a model-backed one for free-text questions."""
        self.gw = gw
        self.extractor = extractor

    # ---------------------------------------------------------------- labels
    def _ref(self, task, outs: dict[str, Out], sid: str, path: str) -> tuple[object, Label]:
        if sid not in outs:
            raise PlanError(f"${sid} is not an earlier step")
        o = outs[sid]
        parts = [p for p in path.split(".") if p]
        try:
            v = _walk(o.value, parts)
        except (KeyError, IndexError, ValueError, TypeError) as e:
            raise PlanError(f"${sid}{path}: {e}") from None
        trust = o.trust
        if o.fields and trust != Trust.UNTRUSTED:
            # a field marked as someone else's free text, or a whole record that contains one, is untrusted
            if (parts and parts[-1] in o.fields) or not parts or isinstance(v, (dict, list)):
                trust = Trust.UNTRUSTED
        if isinstance(v, str) and trust != Trust.TRUSTED and len(v) < 120 and not re.search(r"\s", v) \
                and task.prov.given(v):
            # one value (an address, an account) the user named, or the sender of a message the user asked to reply
            # to; never free text, which may come from that same message
            return v, Label(Trust.TRUSTED, o.conf, ["user", o.source + path])
        return v, Label(trust, o.conf, [o.source + path])

    def _literal(self, task, v) -> Label:
        if isinstance(v, str) and v and task.prov.given(v):
            return Label(Trust.TRUSTED, Conf.PUBLIC, ["user"])
        return Label(Trust.DERIVED, Conf.PUBLIC, ["agent"])

    def resolve(self, task, outs: dict[str, Out], v) -> tuple[object, Label]:
        if isinstance(v, str):
            m = REF.match(v)
            if m:                      # "$name..." always means a reference; an unknown one is a mistake in the plan
                return self._ref(task, outs, m.group(1), m.group(2))
            parts = list(TEMPLATE.finditer(v))
            if parts:
                labs, text, last = [], [], 0
                for p in parts:
                    val, lab = self._ref(task, outs, p.group(1), p.group(2))
                    text += [v[last:p.start()], str(val)]
                    labs.append(lab)
                    last = p.end()
                text.append(v[last:])
                lit = re.sub(TEMPLATE, "", v)
                if lit.strip():
                    labs.append(self._literal(task, lit) if task.prov.given(lit.strip()) else
                                Label(Trust.DERIVED, Conf.PUBLIC, ["agent"]))
                return "".join(text), worst(labs)
            return v, self._literal(task, v)
        if isinstance(v, list):
            pairs = [self.resolve(task, outs, x) for x in v]
            return [p[0] for p in pairs], worst([p[1] for p in pairs])
        if isinstance(v, dict):
            pairs = {k: self.resolve(task, outs, x) for k, x in v.items()}
            return {k: p[0] for k, p in pairs.items()}, worst([p[1] for p in pairs.values()])
        return v, self._literal(task, str(v))

    def extract(self, task, outs: dict[str, Out], spec: dict) -> Out:
        src, lab = self.resolve(task, outs, spec.get("from"))
        kind, question = spec.get("type", "text"), spec.get("question", "")
        text = src if isinstance(src, str) else json.dumps(src, default=str)
        val = None
        if self.extractor is not None:
            val = self.extractor(text, kind, question)
        elif kind in EXTRACTORS:
            m = EXTRACTORS[kind].search(text)
            val = m.group(0) if m else None
        else:
            raise PlanError(f"no extractor for type {kind!r} (pass a model-backed extractor for free text)")
        # the extracted value keeps its source's label: untrusted in, untrusted out
        return Out(val, lab.trust, lab.conf, "extract(" + ",".join(lab.sources) + ")")

    # ---------------------------------------------------------------- run
    def run(self, task_id: str, plan: list[dict]) -> dict:
        task = self.gw.tasks[task_id]
        outs: dict[str, Out] = {}
        steps, status = [], "done"
        self.gw.receipts.append({"type": "plan-mode", "task_id": task_id, "plan": plan})
        for i, step in enumerate(plan):
            sid = str(step.get("id") or f"s{i + 1}")
            if "extract" in step:
                outs[sid] = self.extract(task, outs, step["extract"])
                steps.append({"id": sid, "extract": step["extract"].get("type"), "value": outs[sid].value,
                              "label": outs[sid].trust.value, "source": outs[sid].source})
                continue
            args, flow = {}, {}
            for k, v in (step.get("args") or {}).items():
                args[k], flow[k] = self.resolve(task, outs, v)
            call = ToolCall(str(step.get("tool", "")), args)
            d = self.gw.execute(task_id, self.gw.check(task_id, call, flow=flow))
            steps.append({"id": sid, "tool": call.tool, "args": args, "verdict": d.verdict.value, "reason": d.reason,
                          "labels": {k: {"trust": l.trust.value, "sources": l.sources} for k, l in flow.items()},
                          "receipt": d.receipt_id, "hitl": d.hitl_id, "result_preview": str(d.result)[:300]
                          if d.executed else None})
            if d.verdict == Verdict.DENY:
                status = "blocked"
                break
            if d.verdict == Verdict.ESCALATE:
                status = "waiting"
                break
            spec = self.gw.registry.get(call.tool)
            trust, conf = self.gw.output_label(call)
            outs[sid] = Out(d.result, Trust(trust), conf, f"tool:{call.tool}",
                            tuple(spec.untrusted_fields) if spec else ())
        return {"task_id": task_id, "status": status, "steps": steps}


PLANNER_PROMPT = """You write a plan for a tool-using assistant. You see only the user's request and the tool list,
never any tool's output. Reply with JSON only: {{"plan": [step, ...]}}.
A step is {{"id": "s1", "tool": "<name>", "args": {{...}}}} or {{"id": "e1", "extract": {{"from": "$s1.0.body",
"type": "email|url|number|iban|account|invoice", "question": "..."}}}}.
Refer to earlier outputs as "$s1" or "$s1.0.field"; put them inside text as "{{$s1.0.field}}".
Use only values the user gave for destinations (recipients, accounts, URLs). Don't add steps the user didn't ask for.
Tools:
{tools}"""


class LLMPlanner:
    """Writes a plan with a Qualcomm Cloud AI model, from the request and the tool list only."""

    def __init__(self, llm=None, model: str | None = None):
        from .qualcomm import QualcommCloudAI
        self.llm = llm or QualcommCloudAI(timeout=30.0, max_wait_s=60.0, component="planner")
        self.model = model

    def plan(self, request: str, registry, allowed: list[str]) -> list[dict]:
        tools = "\n".join(f"- {n}({', '.join(f'{k}: {t}' for k, t in s.params.items())}): {s.description}"
                          for n, s in registry.specs.items() if "*" in allowed or n in allowed)
        out = self.llm.chat_json([{"role": "system", "content": PLANNER_PROMPT.format(tools=tools)},
                                  {"role": "user", "content": request}], max_tokens=700, model=self.model)
        plan = out.get("plan")
        if not isinstance(plan, list):
            raise PlanError("the planner did not return a plan")
        return plan
