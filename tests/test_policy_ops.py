"""F9: shadow mode, replay under a draft policy, signed policy bundles, canary rollout."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.models import ToolCall, Verdict  # noqa: E402
from kavach.policy import PolicyEngine  # noqa: E402
from kavach.replay import replay  # noqa: E402

DEFAULT = ROOT / "kavach" / "policies" / "default.yaml"


def gw(**cfg):
    return Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False, **cfg))


def test_shadow_mode_records_but_never_blocks():
    k = gw(enforce=False)
    tid, _ = k.start_task("asha", "support", "The invoices table looks broken, fix it.")
    d = k.check(tid, ToolCall("crm.execute", {"sql": "DROP TABLE invoices"}))
    assert d.verdict == Verdict.ALLOW and d.reason.startswith("[shadow] would have been DENY")
    body = k.receipts.items[-1]["body"]["decision"]
    assert body["shadow"] == {"would_have": "DENY"} and body["policy_sha256"] == PolicyEngine().sha256


def test_replay_shows_what_a_tighter_policy_would_change():
    k = gw()
    tid, _ = k.start_task("asha", "support", "Refund 1500 on invoice 1042; the customer was overcharged.")
    k.check(tid, ToolCall("payments.refund", {"invoice_id": 1042, "amount": 1500}))
    t2, _ = k.start_task("asha", "support", "What is the status of invoice 1042?")
    k.check(t2, ToolCall("crm.query", {"sql": "SELECT status FROM invoices WHERE id = 1042"}))
    draft = PolicyEngine.from_text(DEFAULT.read_text().replace("refund_auto_max: 5000", "refund_auto_max: 1000"))
    out = replay(k, draft)
    assert out["decisions"] == 2 and out["changed"] == 1
    c = out["changes"][0]
    assert c["tool"] == "payments.refund" and c["after"] == "ESCALATE" and c["rule"] == "R5"
    assert replay(k, PolicyEngine())["changed"] == 0                         # the same policy changes nothing


def test_unsigned_or_tampered_policy_refuses_to_load(tmp_path, monkeypatch):
    keys = tmp_path / "keys"
    subprocess.run([sys.executable, "-m", "kavach.receipts", "keygen", str(keys)], check=True, cwd=ROOT,
                   capture_output=True)
    pol = tmp_path / "policy.yaml"
    pol.write_text(DEFAULT.read_text())
    monkeypatch.setenv("KAVACH_POLICY_PUBKEY", str(keys / "kavach_signing.pub.pem"))
    with pytest.raises(PermissionError, match="no signature"):
        PolicyEngine(pol)
    subprocess.run([sys.executable, "-m", "kavach.policy_bundle", "sign", str(pol), "--key",
                    str(keys / "kavach_signing.pem")], check=True, cwd=ROOT, capture_output=True)
    assert PolicyEngine(pol).signed_by
    pol.write_text(pol.read_text().replace("refund_hard_max: 50000", "refund_hard_max: 5000000"))   # tampered
    with pytest.raises(PermissionError, match="does not match"):
        PolicyEngine(pol)


def test_canary_rollout_decides_a_share_of_tasks_with_the_candidate():
    k = gw(candidate_percent=50)
    k.candidate = PolicyEngine.from_text(DEFAULT.read_text().replace("refund_auto_max: 5000", "refund_auto_max: 1000"))
    verdicts = []
    for _ in range(60):
        tid, _ = k.start_task("asha", "support", "Refund 1500 on invoice 1042; the customer was overcharged.")
        d = k.check(tid, ToolCall("payments.refund", {"invoice_id": 1042, "amount": 1500}))
        verdicts.append((k.tasks[tid].policy is not None, d.verdict))
    cand = [v for c, v in verdicts if c]
    assert 15 < len(cand) < 45 and all(v == Verdict.ESCALATE for v in cand)
    assert all(v != Verdict.ESCALATE for c, v in verdicts if not c)
    assert sum(1 for r in k.receipts.items if r["body"].get("decision", {}).get("policy_candidate")) == len(cand)


def test_replay_api(monkeypatch):
    from fastapi.testclient import TestClient

    from kavach import server
    monkeypatch.setattr(server, "AUTH_SECRET", None)
    c = TestClient(server.app)
    c.post("/api/demo/big_refund")
    out = c.post("/api/policy/replay", json={"policy_yaml": DEFAULT.read_text().replace("refund_hard_max: 50000",
                                                                                         "refund_hard_max: 10000")}).json()
    assert any(ch["tool"] == "payments.refund" and ch["after"] == "DENY" for ch in out["changes"])
    assert c.get("/api/policy").json()["sha256"] == PolicyEngine().sha256
