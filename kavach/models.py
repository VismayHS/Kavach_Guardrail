"""Core data model shared by every KAVACH component.

Everything that crosses a component boundary is one of these dataclasses, so the
decision path is fully typed and every receipt can be reconstructed from them.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Trust(str, Enum):
    TRUSTED = "trusted"        # typed by the authenticated user / system config
    DERIVED = "derived"        # produced by the agent itself, no untrusted source matched
    UNTRUSTED = "untrusted"    # came from content the agent read (email, web, file, tool output)


class Conf(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    PII = "pii"

    @property
    def rank(self) -> int:
        return ["public", "internal", "confidential", "pii"].index(self.value)


class Reversibility(str, Enum):
    # Taxonomy from "Revisable by Design" (arXiv 2604.23283), mirrors the saga pattern.
    IDEMPOTENT = "idempotent"
    REVERSIBLE = "reversible"
    COMPENSABLE = "compensable"
    IRREVERSIBLE = "irreversible"

    @property
    def recoverable_fraction(self) -> float:
        return {"idempotent": 1.0, "reversible": 0.95, "compensable": 0.5, "irreversible": 0.0}[self.value]


class Verdict(str, Enum):
    ALLOW = "ALLOW"
    ALLOW_WITH_SAFEGUARD = "ALLOW_WITH_SAFEGUARD"   # executed with snapshot + undo armed
    ESCALATE = "ESCALATE"                           # human-in-the-loop approval required
    DENY = "DENY"                                   # blocked; agent receives a replan hint


@dataclass
class Label:
    """Provenance / information-flow label attached to one argument value."""
    trust: Trust
    conf: Conf
    sources: list[str] = field(default_factory=list)   # e.g. ["user"], ["tool:mail.read_inbox#msg-4471"]
    pii_entities: int = 0                               # number of PII values carried

    def to_dict(self) -> dict:
        return {"trust": self.trust.value, "conf": self.conf.value,
                "sources": self.sources, "pii_entities": self.pii_entities}


@dataclass
class ToolCall:
    tool: str
    args: dict[str, Any]
    call_id: str = field(default_factory=lambda: "call-" + uuid.uuid4().hex[:8])
    tool_def_hash: str | None = None    # hash of the tool definition the agent saw (rug-pull check)


@dataclass
class Principal:
    user_id: str
    role: str                     # e.g. analyst, support, admin
    department: str = "ops"


@dataclass
class TaskContext:
    task_id: str
    principal: Principal
    user_request: str
    env: str = "prod"                                   # prod | staging | dev
    started_at: float = field(default_factory=time.time)
    harm_spent: float = 0.0                             # cumulative expected unrecoverable harm
    denials: int = 0
    plan: list[dict] | None = None
    plan_findings: list[dict] = field(default_factory=list)


@dataclass
class GateResult:
    rule_id: str
    outcome: str          # PASS | DENY | REQUIRE_APPROVAL
    message: str
    evidence: dict = field(default_factory=dict)


@dataclass
class Effect:
    """What the action would do to the world, and how we know it."""
    method: str                      # sandbox | static | predicted
    reversibility: Reversibility
    magnitude: dict[str, Any]        # rows_affected, pii_records, amount, recipients, files...
    harm: float                      # H in [0,1]: normalized severity if the action is wrong
    summary: str
    staged_ms: float = 0.0
    safeguard: str | None = None     # transform available, e.g. "soft-delete", "draft", "hold"


@dataclass
class Risk:
    p_harm: float          # calibrated probability that the action is unsafe / unintended
    p_lo: float            # lower bound of the confidence interval
    p_hi: float            # upper bound
    tau: float             # reversibility-conditioned threshold
    euh: float             # expected unrecoverable harm = p * H * (1 - r)
    features: dict[str, float] = field(default_factory=dict)
    intent: dict = field(default_factory=dict)


@dataclass
class Decision:
    verdict: Verdict
    reason: str
    call: ToolCall
    labels: dict[str, dict]
    gates: list[GateResult]
    effect: Effect | None
    risk: Risk | None
    scorecard: dict[str, dict]
    explanation: str = ""
    replan_hint: str | None = None
    latency_ms: float = 0.0
    receipt_id: str | None = None
    hitl_id: str | None = None
    executed: bool = False
    result: Any = None

    def to_dict(self) -> dict:
        d = {
            "verdict": self.verdict.value,
            "reason": self.reason,
            "call": asdict(self.call),
            "labels": self.labels,
            "gates": [asdict(g) for g in self.gates],
            "effect": None if self.effect is None else {**asdict(self.effect), "reversibility": self.effect.reversibility.value},
            "risk": None if self.risk is None else asdict(self.risk),
            "scorecard": self.scorecard,
            "explanation": self.explanation,
            "replan_hint": self.replan_hint,
            "latency_ms": round(self.latency_ms, 2),
            "receipt_id": self.receipt_id,
            "hitl_id": self.hitl_id,
            "executed": self.executed,
        }
        if self.result is not None:
            d["result_preview"] = str(self.result)[:400]
        return d
