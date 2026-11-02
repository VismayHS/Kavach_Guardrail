"""Pre-demo check (A10): run this 30 minutes before going on stage, and again 5 minutes before.

    python scripts/preflight.py                 # everything; Qualcomm is checked only if a key is set
    python scripts/preflight.py --offline       # pretend the network is down: must still be all green
    python scripts/preflight.py --url http://localhost:8000   # also check the running server

It checks dependencies, the shipped risk model, every demo scenario against its pinned verdicts, undo, the receipt
chain, the auth mode, the offline fallbacks, and warms up the Qualcomm endpoint (GET /models + one tiny call,
timed) so the first call on stage isn't a cold start. Exit code 0 = go, 1 = something to fix.
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESULTS: list[tuple[str, bool, str]] = []
QUALCOMM_VARS = ("IMAGINE_API_KEY", "INFERENCE_CLOUD_API_KEY", "IMAGINE_API_ENDPOINT", "IMAGINE_ENDPOINT_URL",
                 "INFERENCE_CLOUD_ENDPOINT")


def check(name: str):
    def wrap(fn):
        def run(*a, **kw):
            t0 = time.perf_counter()
            try:
                ok, detail = fn(*a, **kw)
            except Exception as e:  # a crashing check is a failed check
                ok, detail = False, f"{type(e).__name__}: {e}"
            RESULTS.append((name, ok, f"{detail} ({(time.perf_counter() - t0) * 1000:.0f} ms)"))
            return ok
        return run
    return wrap


def load_dotenv() -> None:
    """Read ../.env or ./.env (KEY=VALUE lines) without needing python-dotenv."""
    for p in (ROOT / ".env", ROOT.parent / ".env"):
        if p.exists():
            for line in p.read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@check("dependencies")
def deps():
    missing = []
    for m in ("fastapi", "uvicorn", "pydantic", "yaml", "numpy", "sklearn", "httpx", "jwt"):
        try:
            importlib.import_module(m)
        except ImportError:
            missing.append(m)
    return not missing, "all present" if not missing else f"missing: {missing} (pip install -r requirements.txt)"


@check("risk model")
def model():
    from kavach.risk import RiskModel
    r = RiskModel()
    op = r.meta.get("operating_point", {})
    return r.source.startswith("trained") and "c_block" in op, f"{r.source}; C_block={op.get('c_block')}"


@check("demo scenarios match their pinned verdicts")
def scenarios():
    from kavach.environment import Environment
    from kavach.gateway import GatewayConfig, Kavach
    from kavach.risk import RiskModel
    from kavach.scenarios import EXPECTED_FLOWS, SCENARIOS, materialize, prepare
    cfg = GatewayConfig(use_llm_judge=False, c_block=RiskModel().meta["operating_point"]["c_block"])
    k = Kavach(Environment(tempfile.mkdtemp()), cfg)
    bad = []
    for name, sc in SCENARIOS.items():
        prepare(k.env, sc)
        tid, _ = k.start_task(sc["user"][0], sc["user"][1], sc["request"], sc["env"], sc["plan"])
        flow, last = [], None
        for c in sc["steps"]:
            d = k.run(tid, materialize(c, last))
            last = d.result
            rule = d.reason[1:d.reason.index("]")] if d.reason.startswith("[") else None
            flow.append((d.call.tool, d.verdict.value, rule))
            if d.verdict.value in ("DENY", "ESCALATE"):
                break
        if flow != EXPECTED_FLOWS[name]:
            bad.append(name)
    ok = not bad and k.receipts.verify()["valid"]
    return ok, f"{len(SCENARIOS)} scenarios OK, receipt chain valid" if ok else f"changed: {bad}"


@check("undo works (row-level)")
def undo():
    from kavach.environment import Environment
    from kavach.gateway import GatewayConfig, Kavach
    from kavach.models import ToolCall
    k = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    before = k.env.db.execute("SELECT tier FROM customers WHERE id = 5").fetchone()[0]
    new = "silver" if before != "silver" else "bronze"
    tid, _ = k.start_task("asha", "support", f"Please update customer 5 to the {new} tier.")
    d = k.run(tid, ToolCall("crm.execute", {"sql": f"UPDATE customers SET tier = '{new}' WHERE id = 5"}))
    changed = k.env.db.execute("SELECT tier FROM customers WHERE id = 5").fetchone()[0] == new
    out = k.undo_action(d.receipt_id)
    after = k.env.db.execute("SELECT tier FROM customers WHERE id = 5").fetchone()[0]
    ok = changed and out["undone"] and after == before
    return ok, f"verdict {d.verdict.value}: {before!r} -> {new!r} -> undo -> {after!r}"


@check("auth mode")
def auth_mode():
    secret = os.environ.get("KAVACH_AUTH_SECRET")
    if secret and len(secret) >= 32:
        return True, "auth ON (roles come from signed tokens)"
    return True, "auth OFF (dev mode): set KAVACH_AUTH_SECRET before a judge tries to spoof a role"


@check("offline fallbacks (no Qualcomm)")
def offline():
    saved = {k: os.environ.pop(k) for k in QUALCOMM_VARS if k in os.environ}
    try:
        from kavach.environment import Environment
        from kavach.explain import Explainer
        from kavach.gateway import Kavach
        from kavach.qualcomm import QualcommCloudAI
        from kavach.scenarios import SCENARIOS, materialize, prepare
        k = Kavach(Environment(tempfile.mkdtemp()))           # default config: judge ON, but no endpoint
        k.judge.llm, k.explainer = QualcommCloudAI(), Explainer(QualcommCloudAI(), use_llm=True)
        sc = SCENARIOS["email_injection"]
        prepare(k.env, sc)
        tid, _ = k.start_task(sc["user"][0], sc["user"][1], sc["request"], sc["env"], sc["plan"])
        last = d = None
        for c in sc["steps"]:
            d = k.run(tid, materialize(c, last))
            last = d.result
        src = d.risk.intent.get("source", "") if d.risk else ""
        explained = (k.receipts.items[-1]["body"].get("decision") or {}).get("explanation_source", "")
        ok = d.verdict.value == "DENY" and "qualcomm" not in src and explained.startswith("template")
        return ok, f"injection still DENIED offline ({d.reason[:5]}), judge: {src or 'n/a'}, explanation: {explained}"
    finally:
        os.environ.update(saved)


@check("Qualcomm endpoint warm-up")
def qualcomm():
    from kavach.qualcomm import QualcommCloudAI
    q = QualcommCloudAI(timeout=20)
    if not q.enabled:
        return True, "no key set: skipped (the demo runs offline; the judge falls back to the heuristic)"
    t0 = time.perf_counter()
    models = q.models()
    names = list(models.get("llm") or []) + [m.get("id", "") for m in models.get("data") or [] if isinstance(m, dict)]
    t1 = time.perf_counter()
    fast, strong = q.pick_models()
    q.chat_text([{"role": "user", "content": "Reply with the word OK."}], max_tokens=3, model=fast)
    warm = q.last_latency_ms
    return True, f"{len(names)} models; judge {fast} -> {strong}; GET /models {1000 * (t1 - t0):.0f} ms, warm call {warm} ms"


@check("running server")
def server(url: str):
    import httpx
    r = httpx.get(f"{url}/api/receipts/verify", timeout=5)
    s = httpx.get(f"{url}/api/state", timeout=5)
    ok = r.status_code == 200 and r.json().get("valid") and s.status_code in (200, 401)
    return bool(ok), f"{url}: receipts {r.json()}, /api/state {s.status_code}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="hide the Qualcomm key for this run")
    ap.add_argument("--url", help="also check a running KAVACH server")
    a = ap.parse_args()
    load_dotenv()
    if a.offline:
        for k in QUALCOMM_VARS:
            os.environ.pop(k, None)
    deps()
    model()
    scenarios()
    undo()
    auth_mode()
    offline()
    qualcomm()
    if a.url:
        server(a.url)
    width = max(len(n) for n, _, _ in RESULTS)
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    bad = [n for n, ok, _ in RESULTS if not ok]
    print("\nGO" if not bad else f"\nNOT READY: {', '.join(bad)}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
