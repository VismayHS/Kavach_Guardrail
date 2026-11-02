"""F1: delegated agent tokens (RFC 8693 token exchange), the secrets broker, and R32 (no raw keys through agents)."""
import sys
import tempfile
from pathlib import Path

import jwt
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach import auth  # noqa: E402
from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.identity import TOKEN_EXCHANGE, verify_delegated  # noqa: E402
from kavach.models import ToolCall, Verdict  # noqa: E402
from kavach.secret_broker import SecretsBroker, raw_credentials  # noqa: E402
from kavach.signing import load_public  # noqa: E402

SECRET = "kavach-test-secret-at-least-32-bytes-long"


def test_token_exchange_gives_a_short_lived_task_scoped_token(monkeypatch):
    from fastapi.testclient import TestClient

    from kavach import server
    monkeypatch.setattr(server, "AUTH_SECRET", SECRET)
    c = TestClient(server.app)
    user = auth.mint("ravi", "analyst", secret=SECRET)
    r = c.post("/oauth/token", data={"grant_type": TOKEN_EXCHANGE, "subject_token": user, "scope": "mail.send crm.execute",
                                     "audience": "mail-connector", "resource": "task-123", "actor": "agent:outlook-helper"})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["scope"] == "mail.send" and t["expires_in"] == 300               # crm.execute isn't an analyst tool
    pub = load_public(c.get("/api/receipts/public-key").json()["public_key"])
    claims = verify_delegated(t["access_token"], "mail.send", "mail-connector", pub)
    assert claims["sub"] == "ravi" and claims["act"] == {"sub": "agent:outlook-helper"} and claims["task"] == "task-123"
    with pytest.raises(PermissionError):
        verify_delegated(t["access_token"], "crm.execute", "mail-connector", pub)   # not in scope
    with pytest.raises(jwt.InvalidAudienceError):
        verify_delegated(t["access_token"], "mail.send", "payments", pub)
    assert c.get("/.well-known/jwks.json").json()["keys"][0]["crv"] == "Ed25519"
    bad = c.post("/oauth/token", data={"grant_type": TOKEN_EXCHANGE, "subject_token": user, "scope": "payments.transfer"})
    assert bad.status_code == 403
    forged = c.post("/oauth/token", data={"grant_type": TOKEN_EXCHANGE, "scope": "mail.send",
                                          "subject_token": auth.mint("ravi", "admin", secret="x" * 40)})
    assert forged.status_code == 401


def test_raw_credentials_are_blocked_r32():
    k = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    tid, _ = k.start_task("ravi", "analyst", "Email the deploy settings to asha.rao@infycorp.com.")
    for leak in ("AKIAIOSFODNN7EXAMPLE", "sk_" + "live_" + "FAKE0FAKE0FAKE0FAKE0FAKE", "-----BEGIN RSA PRIVATE KEY-----"):
        d = k.check(tid, ToolCall("mail.send", {"to": "asha.rao@infycorp.com", "subject": "s", "body": f"key: {leak}"}))
        assert d.verdict == Verdict.DENY and "R32" in {g.rule_id for g in d.gates if g.outcome == "DENY"}, leak
    ok = k.check(tid, ToolCall("mail.send", {"to": "asha.rao@infycorp.com", "subject": "s", "body": "{{secret:DEPLOY}}"}))
    assert "R32" not in {g.rule_id for g in ok.gates if g.outcome == "DENY"}
    assert raw_credentials({"x": "nothing to see"}) == []


def test_broker_injects_at_execution_and_receipts_keep_the_placeholder():
    k = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    k.secrets = SecretsBroker(environ={"KAVACH_SECRET_NOTES_KEY": "s3cr3t-value"})
    tid, _ = k.start_task("ravi", "analyst", "Append today's action items to notes.txt.")
    d = k.run(tid, ToolCall("files.write", {"path": "notes.txt", "content": "token={{secret:NOTES_KEY}}"}))
    assert d.executed and (k.env.workspace / "notes.txt").read_text() == "token=s3cr3t-value"
    import json
    assert "s3cr3t-value" not in json.dumps(k.receipts.items) and "{{secret:NOTES_KEY}}" in json.dumps(k.receipts.items)
    strict = SecretsBroker(grants={"NOTES_KEY": ["mail.send"]}, environ={"KAVACH_SECRET_NOTES_KEY": "v"})
    with pytest.raises(PermissionError):
        strict.resolve("files.write", {"content": "{{secret:NOTES_KEY}}"})
