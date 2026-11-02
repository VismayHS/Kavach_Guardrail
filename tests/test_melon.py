"""C1 MELON: masked re-execution. If the agent still proposes a state-changing call with the user's request masked
out, the call is driven by what it read: R27 sends it to a person (never a denial)."""
import json
import tempfile

from kavach.environment import Environment
from kavach.gateway import GatewayConfig, Kavach
from kavach.melon import NEUTRAL, Melon, similarity
from kavach.models import ToolCall, Verdict

CONVO = [{"role": "system", "content": "You are an assistant."},
         {"role": "user", "content": "Email john.menon@client4.com that invoice 1042 is being processed."},
         {"role": "assistant", "content": "", "tool_calls": [{"id": "a", "type": "function", "function": {
             "name": "mail__read_inbox", "arguments": "{}"}}]},
         {"role": "tool", "tool_call_id": "a", "content": "[...the inbox...]"}]


def proposes(name, args):
    return lambda messages, tools: {"role": "assistant", "content": "", "tool_calls": [
        {"id": "m", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def test_masking_replaces_only_the_users_turns():
    m = Melon.masked(CONVO)
    assert m[1] == {"role": "user", "content": NEUTRAL} and m[0] == CONVO[0] and m[2:] == CONVO[2:]


def test_similarity():
    a = {"to": "x@y.io", "subject": "s", "body": "b"}
    assert similarity("mail.send", a, "mail.send", dict(a)) == 1.0
    assert similarity("mail.send", a, "mail.send", {**a, "body": "other"}) == 2 / 3
    assert similarity("mail.send", a, "payments.transfer", a) == 0.0


def decide(chat, call):
    gw = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    tid, _ = gw.start_task("ravi", "analyst", CONVO[1]["content"])
    mel = Melon(chat, name_map=lambda n: n.replace("__", "."))
    return gw.check(tid, call, melon=lambda c: mel.check(CONVO, [], c.tool, c.args)), mel


SEND = ToolCall("mail.send", {"to": "john.menon@client4.com", "subject": "Invoice 1042",
                              "body": "Hi John, invoice 1042 is being processed. Regards, Ravi"})


def test_a_call_the_masked_run_repeats_goes_to_a_person():
    d, mel = decide(proposes("mail__send", SEND.args), SEND)
    r27 = next(g for g in d.gates if g.rule_id == "R27")
    assert r27.outcome == "REQUIRE_APPROVAL" and d.verdict == Verdict.ESCALATE and mel.matches == 1


def test_a_call_only_the_user_asked_for_is_unaffected():
    d, mel = decide(lambda m, t: {"role": "assistant", "content": "The inbox has three emails."}, SEND)
    assert next(g for g in d.gates if g.rule_id == "R27").outcome == "PASS"
    assert d.verdict == Verdict.ALLOW_WITH_SAFEGUARD and mel.calls == 1


def test_a_model_failure_never_blocks():
    def boom(m, t):
        raise TimeoutError("model down")
    d, mel = decide(boom, SEND)
    g = next(g for g in d.gates if g.rule_id == "R27")
    assert g.outcome == "PASS" and "unavailable" in g.message and d.verdict == Verdict.ALLOW_WITH_SAFEGUARD


def test_reads_and_denied_calls_cost_no_model_call():
    calls = []
    gw = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    tid, _ = gw.start_task("ravi", "analyst", "Summarise my inbox.")
    probe = lambda c: calls.append(c) or {"match": True}               # noqa: E731
    gw.check(tid, ToolCall("mail.read_inbox", {}), melon=probe)
    d = gw.check(tid, ToolCall("files.read", {"path": "deploy.env"}), melon=probe)
    assert d.verdict == Verdict.DENY and calls == []
