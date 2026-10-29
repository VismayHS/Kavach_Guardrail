"""Plan validator: checks the agent's whole plan before step one.

Per-call checks miss multi-step attacks: "read customers" and "send email" each look
fine, together they are exfiltration (the "lethal trifecta": private data +
untrusted content + external communication; Willison 2025). The plan validator
finds these paths up front, then every step is still re-validated at runtime
because later arguments depend on earlier outputs.
"""
from __future__ import annotations

from .intent import heuristic_alignment
from .manifest import ToolRegistry


def validate_plan(plan: list[dict], user_request: str, role_tools: list[str], registry: ToolRegistry) -> dict:
    findings, seen_untrusted, seen_private = [], None, None
    irreversible, sinks = 0, 0
    for i, step in enumerate(plan, 1):
        tool = step.get("tool")
        spec = registry.get(tool)
        if spec is None:
            findings.append({"step": i, "level": "DENY", "code": "P4", "msg": f"Unknown tool '{tool}'."})
            continue
        if "*" not in role_tools and tool not in role_tools:
            findings.append({"step": i, "level": "DENY", "code": "P3", "msg": f"Role may not use {tool}."})
        if spec.output_trust == "untrusted" and seen_untrusted is None:
            seen_untrusted = i
        if spec.output_conf.value in ("pii", "confidential") or tool == "files.read":
            seen_private = seen_private or i
        if spec.reversibility.value == "irreversible":
            irreversible += 1
        if spec.sink == "external":
            sinks += 1
            if seen_untrusted and seen_private:
                findings.append({"step": i, "level": "CAUTION", "code": "P1",
                                 "msg": f"Lethal-trifecta path: untrusted input (step {seen_untrusted}) + private "
                                        f"data (step {seen_private}) + external sink (step {i}). Destination "
                                        "arguments must trace to the user at runtime."})
        al = heuristic_alignment(user_request, tool, {})
        if al["alignment"] < 0.6 and spec.effect not in ("read", "ingress"):
            findings.append({"step": i, "level": "CAUTION", "code": "P5",
                             "msg": f"Step {i} ({tool}) is a state-changing action the request does not ask for."})
    verdict = "DENY" if any(f["level"] == "DENY" for f in findings) else \
        "CAUTION" if findings else "OK"
    return {"verdict": verdict, "findings": findings,
            "forecast": {"steps": len(plan), "irreversible_steps": irreversible, "external_sinks": sinks}}
