"""F10: tenants. A token's tenant tags its tasks and receipts; callers see and approve only their own tenant's;
a tenant can have its own policy."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach import auth  # noqa: E402
from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.models import ToolCall, Verdict  # noqa: E402
from kavach.policy import PolicyEngine  # noqa: E402

SECRET = "kavach-test-secret-at-least-32-bytes-long"
DEFAULT = Path(__file__).resolve().parents[1] / "kavach" / "policies" / "default.yaml"


def test_a_tenant_can_have_its_own_policy():
    k = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    k.tenant_policies["acme"] = PolicyEngine.from_text(DEFAULT.read_text().replace("refund_auto_max: 5000",
                                                                                   "refund_auto_max: 1000"))
    call = ToolCall("payments.refund", {"invoice_id": 1042, "amount": 1500})
    req = "Refund 1500 on invoice 1042; the customer was overcharged."
    a, _ = k.start_task("asha", "support", req, tenant="acme")
    b, _ = k.start_task("asha", "support", req, tenant="globex")
    assert k.check(a, call).verdict == Verdict.ESCALATE and k.check(b, call).verdict != Verdict.ESCALATE
    assert k.receipts.items[-1]["body"]["tenant"] == "globex"


def test_callers_see_and_approve_only_their_own_tenant(monkeypatch):
    from fastapi.testclient import TestClient

    from kavach import server
    monkeypatch.setattr(server, "AUTH_SECRET", SECRET)
    c = TestClient(server.app)
    hdr = lambda u, r, t: {"Authorization": "Bearer " + auth.mint(u, r, secret=SECRET, tenant=t)}  # noqa: E731
    acme, globex = hdr("asha", "support", "acme"), hdr("bob", "support", "globex")
    r = c.post("/api/v1/check", headers=acme, json={
        "user_request": "Refund 12000 on invoice 1042, the customer was double charged.", "tool": "payments.refund",
        "args": {"invoice_id": 1042, "amount": 12000}}).json()
    assert r["verdict"] == "ESCALATE"
    assert r["task_id"] in [t["task_id"] for t in c.get("/api/tasks", headers=acme).json()]
    assert r["task_id"] not in [t["task_id"] for t in c.get("/api/tasks", headers=globex).json()]
    assert c.get(f"/api/tasks/{r['task_id']}", headers=globex).status_code == 404
    assert r["hitl_id"] not in [i["id"] for i in c.get("/api/hitl", headers=globex).json()]
    assert c.post(f"/api/hitl/{r['hitl_id']}", headers=hdr("eve", "support", "globex"),
                  json={"approve": True}).status_code == 403
    assert all(x["body"].get("tenant") in (None, "acme") or x["body"]["type"] != "decision"
               for x in c.get("/api/receipts?limit=1000", headers=acme).json())
    assert c.get("/api/receipts/export", headers=acme).status_code == 403
    assert r["task_id"] in [t["task_id"] for t in c.get("/api/tasks", headers=hdr("ops", "admin", "x")).json()]
