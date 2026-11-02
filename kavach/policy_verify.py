"""Verify KAVACH's Cedar policies (E4): proofs by partial evaluation, and parity with the Python engine.

    python -m kavach.policy_verify          # prints the proofs and parity, writes bench/results/CEDAR.md

A proof fixes only the facts a property is about and leaves every other fact unknown; Cedar's partial evaluator
returning a definite Deny means the property holds for every value of the unknowns. Each property is about the Cedar
policies; the parity run shows the Cedar policies and the Python engine reach the same outcome on every decision of
the bench suite, the holdout and the demo scenarios.
"""
from __future__ import annotations

import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROPERTIES = [   # (claim, fixed facts, action that must be denied)
    ("Untrusted content the user didn't point at can never choose where an external action goes (R1)",
     {"external": True, "ingress": False, "refused_control": True}, "execute"),
    ("A destination read from a source the user pointed at never runs without a person (R1)",
     {"external": True, "ingress": False, "delegated_control": True}, "auto_execute"),
    ("No schema-destructive SQL in production, whatever else is true (R4)",
     {"prod": True, "sql_write": True, "ddl": True}, "execute"),
    ("A planted canary record never leaves the company (R28)",
     {"outbound": True, "carries_canary": True}, "execute"),
    ("A paused agent can do nothing at all (kill switch)", {"killed": True}, "execute"),
    ("Whoever proposed a payment can never release it (R19, separation of duties)",
     {"ap_release": True, "self_proposed": True}, "execute"),
    ("Vendor bank details never change on the say-so of an email or document (R20)",
     {"bank_change": True, "iban_untrusted": True}, "execute"),
    ("Credential files are never read into an agent's context (R9)",
     {"file_read": True, "sensitive_path": True}, "execute"),
    ("Once a task holds private data and untrusted content, an outbound action to a destination the user didn't "
     "give never runs without a person (R14)",
     {"external": True, "private_seen": True, "untrusted_seen": True, "destination_trusted": False,
      "internal_destination": False}, "auto_execute"),
    ("A EUR 650,000 release never runs without a person when the releaser's limit is EUR 25,000 (R18; for these "
     "amounts, not every amount)", {"ap_release": True, "amount": 65_000_000, "role_release_limit": 2_500_000},
     "auto_execute"),
    ("A tool onboarded from MCP annotations never runs without a person until approved (R6)",
     {"draft_tool": True}, "auto_execute"),
]


def prove_all(policy) -> list[dict]:
    out = []
    for claim, fixed, action in PROPERTIES:
        r = policy.prove(fixed, action)
        out.append({"claim": claim, "fixed": fixed, "action": action, **r})
    return out


def control(policy) -> dict:
    """Not vacuous: a clean read with every fact known is allowed, and so is the same call fully automatically."""
    from .cedar_policy import BOOL_FACTS, INT_FACTS
    clean = {k: False for k in BOOL_FACTS} | {k: 0 for k in INT_FACTS}
    clean.update(known_tool=True, role_allowed=True, pii_external_max=1, bulk_rows_approval=50)
    return policy.decide(clean)


def parity() -> dict:
    sys.path.insert(0, str(ROOT))
    from bench.holdout import generate as holdout
    from bench.suite import generate, materialize, prepare

    from .environment import Environment
    from .gateway import GatewayConfig, Kavach
    from .risk import RiskModel
    from .scenarios import SCENARIOS
    from .scenarios import materialize as demo_materialize
    from .scenarios import prepare as demo_prepare
    env = Environment(tempfile.mkdtemp())
    k = Kavach(env, GatewayConfig(use_llm_judge=False, cedar="shadow",
                                  c_block=RiskModel().meta["operating_point"]["c_block"]))
    notes = []
    for sc in generate(n_per_family=20, seed=11) + holdout():
        prepare(env, sc)
        tid, _ = k.start_task(sc.user[0], sc.user[1], sc.request, sc.env)
        outs = []
        for call in sc.setup:
            o = env.dispatch(call.tool, call.args)
            k.register_output(tid, call, o)
            outs.append(o)
        k.check(tid, materialize(sc.action, outs))
        notes.append((sc.family, k.receipts.items[-1]["body"]["decision"]["cedar"]))
    for name, sc in SCENARIOS.items():
        demo_prepare(env, sc)
        tid, _ = k.start_task(sc["user"][0], sc["user"][1], sc["request"], sc["env"], sc["plan"])
        last = None
        for c in sc["steps"]:
            d = k.run(tid, demo_materialize(c, last))
            last = d.result
            notes.append((f"demo:{name}", k.receipts.items[-1 if not d.executed else -2]["body"]["decision"]["cedar"]))
    floors = Counter(n["floor"] for _, n in notes)
    rules = Counter(r for _, n in notes for r in n["rules"])
    return {"decisions": len(notes), "agree": sum(n["agrees"] for _, n in notes), "floors": dict(floors),
            "rules_exercised": dict(rules.most_common()),
            "disagreements": [(f, n) for f, n in notes if not n["agrees"]][:20]}


def main() -> int:
    from .cedar_policy import CedarPolicy
    policy = CedarPolicy()
    proofs, ctl, par = prove_all(policy), control(policy), parity()
    lines = ["# KAVACH policies in Cedar: proofs and parity", "",
             "Policies: `kavach/policies/cedar/kavach.cedar`. Facts come from KAVACH's engines (provenance, staging, "
             "lookalike and canary checks); Cedar decides. Method: Cedar's partial evaluator, with only the facts a "
             "property is about fixed and every other fact unknown; a definite Deny holds for every value of the "
             "unknowns. This is not Cedar's SMT analyzer (the Rust cedar-symcc tool), and partial evaluation is an "
             "experimental upstream feature.", "", "## Proofs", "", "| Property | Result |", "|---|---|"]
    lines += [f"| {p['claim']} | {'**proved**' if p['proved'] else 'NOT proved: ' + p['decision']} |" for p in proofs]
    lines += ["", f"Control (not vacuous): a clean read with every fact known gets `{ctl['verdict_floor']}`.", "",
              "## Parity with the Python engine", "",
              f"{par['agree']} of {par['decisions']} decisions agree (bench suite, holdout, demo scenarios). "
              f"Cedar floors: {par['floors']}.", "", "Rules exercised: " +
              ", ".join(f"{r} x{n}" for r, n in par["rules_exercised"].items()) + ".", ""]
    if par["disagreements"]:
        lines += ["Disagreements:", ""] + [f"- {f}: {n}" for f, n in par["disagreements"]]
    text = "\n".join(lines) + "\n"
    (ROOT / "bench" / "results" / "CEDAR.md").write_text(text)
    print(text)
    return 0 if all(p["proved"] for p in proofs) and par["agree"] == par["decisions"] and \
        ctl["verdict_floor"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
