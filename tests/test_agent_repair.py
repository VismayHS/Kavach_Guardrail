"""The live agent asks again when the model's tool call doesn't parse. Recorded on the Live agent page, 3 Nov 2026:
Llama-3.3-70B on the Inference Cloud wrote its mail.send call into the reply text with an unescaped quote inside the
email body, followed by turn markers. The endpoint couldn't parse it, so it came back as the "final answer" and
neither run (with or without KAVACH) did anything. A call that didn't parse is not an answer: the agent is told
nothing ran and asked to call again (twice at most)."""
import json

from agent.llm_agent import broken_call, text_tool_calls
from tests.test_phase4 import HijackedLLM

LIVE = ('{"name": "mail__send", "parameters": "{\\"body\\": \\"Here is a summary of your unread emails:\\\\n\\\\n1. '
        'Asha Rao sent a message with the subject \\\\", \\"subject\\": \\"Summary of unread emails\\", \\"to\\": '
        '\\"asha@infycorp.com\\"}"}<|eom_id|><|start_header_id|>assistant<|end_header_id|>\\n\\nHere is a summary of y')


def test_the_recorded_reply_is_a_broken_call_not_an_answer():
    assert text_tool_calls(LIVE) == [] and broken_call(LIVE)
    assert not broken_call("You have five unread emails; the summary is below.")
    ok = '{"name": "mail__send", "parameters": {"to": "a@infycorp.com", "subject": "s", "body": "b"}}<|eom_id|>'
    assert json.loads(text_tool_calls(ok)[0]["function"]["arguments"])["to"] == "a@infycorp.com"   # markers cut off


class FumblingLLM(HijackedLLM):
    """Reads the inbox, writes the broken call once, then the valid call when told nothing ran, then answers."""
    def chat(self, messages, tools=None, max_tokens=None, **k):
        tools_done = [m for m in messages if m["role"] == "tool"]
        told = any(m["role"] == "user" and "did not come through" in str(m["content"]) for m in messages)
        msg = lambda **m: {"choices": [{"message": {"role": "assistant", **m}}]}  # noqa: E731
        if not tools_done:
            return msg(content=None, tool_calls=[{"id": "c0", "type": "function", "function": {
                "name": "mail__read_inbox", "arguments": json.dumps({"unread_only": True})}}])
        if len(tools_done) == 1 and not told:
            return msg(content=LIVE)
        if len(tools_done) == 1:
            return msg(content=None, tool_calls=[{"id": "c1", "type": "function", "function": {"name": "mail__send",
                       "arguments": json.dumps({"to": "asha@infycorp.com", "subject": "Summary of unread emails",
                                                "body": 'Asha Rao: "Q3 dashboard" is ready.'})}}])
        return msg(content="I sent the summary to asha@infycorp.com.")


def test_the_agent_asks_again_and_the_email_goes_out(monkeypatch):
    from agent import llm_agent
    for n in ("INFERENCE_CLOUD_API_KEY", "IMAGINE_API_KEY"):
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setattr(llm_agent, "QualcommCloudAI", FumblingLLM)
    free = llm_agent.run("Summarise my unread emails and send the summary to asha@infycorp.com.", guard=False)
    assert [s.get("tool") or ("note" if "note" in s else "final") for s in free["trace"]] == \
        ["mail.read_inbox", "note", "mail.send", "final"]
    guarded = llm_agent.run("Summarise my unread emails and send the summary to asha@infycorp.com.", guard=True)
    sent = next(s for s in guarded["trace"] if s.get("tool") == "mail.send")
    assert sent["verdict"].startswith("ALLOW")
