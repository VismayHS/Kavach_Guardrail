import sys, tempfile
sys.path.insert(0, ".")
from kavach.environment import Environment
from kavach.gateway import Kavach
from kavach.scenarios import SCENARIOS, materialize

env = Environment(tempfile.mkdtemp())
k = Kavach(env)
for name, sc in SCENARIOS.items():
    env.reset()
    tid, plan = k.start_task(sc["user"][0], sc["user"][1], sc["request"], sc["env"], sc["plan"])
    print(f"\n=== {name}: {sc['title']}  | plan: {plan['verdict']} {[f['code'] for f in plan['findings']]}")
    last = None
    for call in sc["steps"]:
        call = materialize(call, last)
        d = k.run(tid, call)
        r = d.risk
        print(f"  {d.verdict.value:22s} {call.tool:18s} {d.latency_ms:6.1f}ms  " +
              (f"p={r.p_harm:.2f}[{r.p_lo:.2f},{r.p_hi:.2f}] tau={r.tau:.3f} H={d.effect.harm:.2f}" if r else "") +
              f"  | {d.reason[:110]}")
        last = d.result
print("\nreceipts:", k.receipts.verify())
