"""KAVACH_PROFILE=prod refuses to start in demo mode (no auth secret, the demo receipt key, no signing key) and turns
off what only a demo may do: the demo endpoints, fast-forwarding a window, Start over. With auth on, approving,
pausing and Send now on a payment need a signed token with the right role."""
import pytest

from kavach.profile import ProfileError, check_profile

GOOD = {"KAVACH_PROFILE": "prod", "KAVACH_AUTH_SECRET": "a" * 40, "KAVACH_RECEIPT_KEY": "b" * 40,
        "KAVACH_SIGNING_KEY": "/keys/kavach_signing.pem"}


@pytest.mark.parametrize("missing", ["KAVACH_AUTH_SECRET", "KAVACH_RECEIPT_KEY", "KAVACH_SIGNING_KEY"])
def test_prod_refuses_to_start_without_each_secret(missing):
    with pytest.raises(ProfileError, match=missing):
        check_profile({k: v for k, v in GOOD.items() if k != missing})


def test_prod_refuses_the_demo_receipt_key():
    with pytest.raises(ProfileError, match="KAVACH_RECEIPT_KEY"):
        check_profile({**GOOD, "KAVACH_RECEIPT_KEY": "demo-receipt-key"})


def test_prod_turns_off_the_demo_only_routes():
    p = check_profile(GOOD)
    assert p.prod and p.require_tool_hash and not p.demo_endpoints and not p.fast_forward
    d = check_profile({})
    assert d.name == "dev" and d.demo_endpoints and d.fast_forward


def test_reset_fast_forward_and_demo_routes_refuse_in_prod(monkeypatch):
    from fastapi.testclient import TestClient

    from kavach import server
    monkeypatch.setattr(server, "PROFILE", check_profile(GOOD))
    c = TestClient(server.app)
    assert c.post("/api/stage/reset").status_code == 403
    assert c.post("/api/settle?advance_s=3600").status_code == 403
    assert c.post("/api/demo/side-by-side").status_code == 404
