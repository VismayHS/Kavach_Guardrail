"""The shared Qualcomm client waits out rate limits (as long as the service asks) within its budget."""
import httpx
import pytest

from kavach import qualcomm


class Resp:
    def __init__(self, code, text="", headers=None):
        self.status_code, self.text, self.headers = code, text, headers or {}
        self.request = httpx.Request("POST", "http://x")

    def json(self):
        return {"choices": [{"message": {"content": "OK"}}]}


def client(monkeypatch, responses, max_wait_s):
    seq, slept = list(responses), []
    monkeypatch.setattr(qualcomm.httpx, "post", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(qualcomm.time, "sleep", lambda s: slept.append(s))
    return qualcomm.QualcommCloudAI(endpoint="http://x", api_key="k", max_wait_s=max_wait_s), slept


def test_a_rate_limit_is_waited_out_as_long_as_the_service_asks(monkeypatch):
    c, slept = client(monkeypatch, [Resp(429, '{"message": "Please wait 19.00 seconds before retrying."}'),
                                    Resp(503), Resp(200)], max_wait_s=120)
    assert c.chat_text([{"role": "user", "content": "hi"}]) == "OK"
    assert slept[0] >= 20 and c.rate_limited == 1 and c.retries == 2


def test_a_short_budget_gives_up_fast(monkeypatch):
    c, slept = client(monkeypatch, [Resp(429, "Please wait 19.00 seconds")], max_wait_s=4)
    with pytest.raises(httpx.HTTPStatusError):
        c.chat_text([{"role": "user", "content": "hi"}])
    assert slept == []                                      # the judge never blocks a decision for 20 s


def test_client_errors_are_not_retried(monkeypatch):
    c, slept = client(monkeypatch, [Resp(400, "bad request")], max_wait_s=60)
    with pytest.raises(httpx.HTTPStatusError):
        c.chat_text([{"role": "user", "content": "hi"}])
    assert slept == []


def test_a_hung_connection_is_retried_at_once(monkeypatch):
    seq, slept = [httpx.ConnectTimeout("hung"), Resp(200)], []

    def post(*a, **k):
        x = seq.pop(0)
        if isinstance(x, Exception):
            raise x
        return x
    monkeypatch.setattr(qualcomm.httpx, "post", post)
    monkeypatch.setattr(qualcomm.time, "sleep", lambda s: slept.append(s))
    c = qualcomm.QualcommCloudAI(endpoint="http://x", api_key="k", max_wait_s=30)
    assert c.chat_text([{"role": "user", "content": "hi"}]) == "OK" and slept and slept[0] < 2.1
