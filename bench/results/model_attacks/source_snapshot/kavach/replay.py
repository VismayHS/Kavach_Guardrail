"""Replay past tasks under a draft policy (F9): "what would this change have done last week?"

The gateway keeps, per task, what the agent was asked, what each tool returned, and every call it checked (in memory,
never exported: outputs may hold personal data). replay() runs those events through a fresh gateway with the draft
policy (deciding only, nothing executes) and lists every decision that would change.
"""
from __future__ import annotations

import tempfile
from collections import Counter

from .environment import Environment
from .gateway import GatewayConfig, Kavach
from .manifest import ToolRegistry
from .models import ToolCall


def replay(gw: Kavach, draft, task_ids: list[str] | None = None) -> dict:
    sim = Kavach(Environment(tempfile.mkdtemp(prefix="kavach-replay-")),
                 GatewayConfig(use_llm_judge=False, local_execution=False, c_block=gw.cfg.c_block,
                               harm_budget=gw.cfg.harm_budget, circuit_breaker=gw.cfg.circuit_breaker),
                 policy=draft, registry=ToolRegistry(dict(gw.registry.specs)), risk=gw.risk)
    sim.registry.pins.update(gw.registry.pins)
    sim.registry.drafts |= gw.registry.drafts
    changed, n, by = [], 0, Counter()
    for old_tid in (task_ids or list(gw.events)):
        new_tid = None
        for ev in gw.events.get(old_tid, []):
            if ev["e"] == "start":
                new_tid, _ = sim.start_task(ev["user"], ev["role"], ev["request"], ev["env"],
                                            authenticated=ev.get("authenticated", False))
            elif new_tid is None:
                continue
            elif ev["e"] == "output":
                sim.register_output(new_tid, ToolCall(ev["tool"], ev["args"]), ev["output"])
            elif ev["e"] == "check":
                d = sim.check(new_tid, ToolCall(ev["tool"], ev["args"], tool_def_hash=ev.get("tool_def_hash")))
                n += 1
                before = ev.get("would_have") or ev["verdict"]
                if d.verdict.value != before:
                    rule = d.reason[1:d.reason.index("]")] if d.reason.startswith("[") else None
                    by[(before, d.verdict.value)] += 1
                    changed.append({"task": old_tid, "receipt": ev.get("receipt"), "tool": ev["tool"],
                                    "before": before, "after": d.verdict.value, "rule": rule, "reason": d.reason[:200]})
    return {"tasks": len(task_ids or gw.events), "decisions": n, "changed": len(changed),
            "transitions": {f"{a} -> {b}": c for (a, b), c in by.most_common()}, "changes": changed[:200]}
