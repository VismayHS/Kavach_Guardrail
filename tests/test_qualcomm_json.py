"""chat_json on Qualcomm's endpoint. Its tool-call parser reads a reply that starts with "{" as a tool call and drops
it: asked for JSON, Llama-3.3-70B came back with content "" and one nameless call with arguments "{}" (live, 3 Nov),
so the red team's attacker and the planner got nothing. JSON now comes back through a forced 'answer' tool."""
import pytest

from kavach import qualcomm


def client(monkeypatch, reply):
    sent = []

    def post(self, path, body):
        sent.append(body)
        return reply(body)
    monkeypatch.setattr(qualcomm.QualcommCloudAI, "_post", post)
    return qualcomm.QualcommCloudAI(model="Llama-3.3-70B", api_key="x", endpoint="https://example.test/v2"), sent


def endpoint_like_qualcomm(body):
    """Answers {"ok": true} the way the real endpoint does: forced tool -> its arguments; otherwise swallowed."""
    forced = (body.get("tool_choice") or {}).get("function", {}).get("name") if isinstance(body.get("tool_choice"), dict) else None
    call = {"function": {"name": forced or "", "arguments": '{"ok": true}' if forced else "{}"}}
    return {"choices": [{"finish_reason": "tool_calls", "message": {"content": "", "tool_calls": [call]}}]}


def test_json_comes_back_through_the_forced_answer_tool(monkeypatch):
    llm, sent = client(monkeypatch, endpoint_like_qualcomm)
    assert llm.chat_json([{"role": "user", "content": "Reply with JSON: ok true"}]) == {"ok": True}
    assert sent[0]["tool_choice"]["function"]["name"] == "answer" and sent[0]["tools"][0]["function"]["name"] == "answer"


def test_a_server_that_answers_in_text_still_works(monkeypatch):
    llm, _ = client(monkeypatch, lambda b: {"choices": [{"message": {"content": 'Sure: {"ok": true}'}}]})
    assert llm.chat_json([{"role": "user", "content": "x"}]) == {"ok": True}


def test_a_swallowed_reply_is_a_clear_error(monkeypatch):
    llm, _ = client(monkeypatch, lambda b: {"choices": [{"message": {"content": "", "tool_calls": [
        {"function": {"name": "", "arguments": "{}"}}]}}]})
    with pytest.raises(ValueError, match="no JSON"):
        llm.chat_json([{"role": "user", "content": "x"}])


def test_a_server_that_rejects_tools_is_asked_again_without_them(monkeypatch):
    def reply(body):
        if "tools" in body:
            raise qualcomm.httpx.HTTPStatusError("400 tools not supported", request=None, response=None)
        return {"choices": [{"message": {"content": '{"ok": true}'}}]}
    llm, sent = client(monkeypatch, reply)
    assert llm.chat_json([{"role": "user", "content": "x"}]) == {"ok": True} and len(sent) == 2
