"""Cedar and the Python engine agree on every scenario family of the bench corpus and the holdout (a sample of each,
so it runs with the tests). Before this test the corpus parity was a script, and a Python-only change to R1 left 13
decisions disagreeing unseen. The full corpus: `python -m kavach.policy_verify`."""
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("cedarpy")

from bench.holdout import generate as holdout  # noqa: E402
from bench.suite import generate, materialize, prepare  # noqa: E402
from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.risk import RiskModel  # noqa: E402


def test_cedar_agrees_with_python_on_every_family():
    env = Environment(tempfile.mkdtemp())
    c_block = RiskModel().meta["operating_point"]["c_block"]
    k = Kavach(env, GatewayConfig(use_llm_judge=False, c_block=c_block, cedar="shadow"))
    bad, families = [], Counter()
    for sc in generate(n_per_family=3, seed=11) + holdout(n=4):
        prepare(env, sc)
        tid, _ = k.start_task(sc.user[0], sc.user[1], sc.request, sc.env)
        outs = []
        for call in sc.setup:
            o = env.dispatch(call.tool, call.args)
            k.register_output(tid, call, o)
            outs.append(o)
        d = k.check(tid, materialize(sc.action, outs))
        note = k.receipts.items[-1]["body"]["decision"]["cedar"]
        families[sc.family] += 1
        if not note["agrees"]:
            bad.append((sc.family, sorted({(g.rule_id, g.outcome) for g in d.gates if g.outcome != "PASS"}),
                        note["rules"]))
    assert len(families) >= 40 and not bad, bad[:5]
