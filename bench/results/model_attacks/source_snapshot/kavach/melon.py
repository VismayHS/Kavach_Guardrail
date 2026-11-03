"""MELON, masked re-execution (C1): is this action driven by the user, or by something the agent read?

After Zhu et al., "MELON: Provable Defense Against Indirect Prompt Injection Attacks in AI Agents" (ICML 2025). When
the agent proposes a state-changing call, the same model is asked for its next step once more, on the same
conversation, but with every user turn replaced by a task-neutral instruction ("summarise the tool outputs"). If the
model *still* proposes the same call (same tool, same key arguments), the call cannot be coming from the user: the
tool outputs are driving it, which is what an indirect prompt injection does.

In KAVACH this is a model signal, so it never blocks on its own: a match adds rule R27 at REQUIRE_APPROVAL strength
(the action goes to a person), and no match changes nothing. Only deterministic rules deny.

Scope: it needs the agent's conversation, so it runs where KAVACH sees it: our own agent (agent/llm_agent.py,
KAVACH_MELON=1) and the AgentDojo pipeline (defense "kavach_melon"). The plain /api/v1/check API and the hooks see
single calls and can't use it. Cost: one extra model call per state-changing call that the rules let through
(counted in `calls` and `ms`).
"""
from __future__ import annotations

import json
import re
import time
from typing import Callable

NEUTRAL = ("Please summarise the contents of the tool outputs above. If they ask you to take an action, take it "
           "with the tools.")


def _norm(v) -> str:
    return re.sub(r"\s+", " ", json.dumps(v, sort_keys=True, default=str) if not isinstance(v, str) else v).strip().lower()


def similarity(name: str, args: dict, other_name: str, other_args: dict) -> float:
    """1.0 for the same tool with the same arguments; the share of matching argument values otherwise."""
    if name != other_name:
        return 0.0
    if not args:
        return 1.0
    same = sum(1 for k, v in args.items() if k in other_args and _norm(other_args[k]) == _norm(v))
    return same / len(args)


def tool_calls(msg: dict) -> list[tuple[str, dict]]:
    """(name, args) of every call in an OpenAI-format assistant message, including calls written as text."""
    raw = msg.get("tool_calls") or []
    if not raw and msg.get("content"):
        from agent.llm_agent import text_tool_calls
        raw = text_tool_calls(msg.get("content"))
    out = []
    for c in raw:
        f = c.get("function") or {}
        a = f.get("arguments") or "{}"
        try:
            a = json.loads(a) if isinstance(a, str) else dict(a)
        except (json.JSONDecodeError, TypeError, ValueError):
            a = {}
        out.append((str(f.get("name", "")), a if isinstance(a, dict) else {}))
    return out


class Melon:
    def __init__(self, chat: Callable[[list[dict], list[dict]], dict], threshold: float = 0.5,
                 name_map: Callable[[str], str] | None = None):
        """chat(messages, tools) -> the model's OpenAI-format assistant message. name_map turns a model-side tool
        name into KAVACH's (e.g. "mail__send" -> "mail.send")."""
        self.chat, self.threshold = chat, threshold
        self.name_map = name_map or (lambda n: n)
        self.calls, self.ms, self.matches, self.errors = 0, [], 0, 0

    @staticmethod
    def masked(messages: list[dict]) -> list[dict]:
        """The conversation with every user turn replaced by the task-neutral instruction; system prompt, the
        agent's earlier calls and the tool outputs stay as they were."""
        return [{"role": "user", "content": NEUTRAL} if m.get("role") == "user" else m for m in messages]

    def check(self, messages: list[dict], tools: list[dict], name: str, args: dict) -> dict:
        """messages: the conversation *before* the assistant turn that proposed this call."""
        t0 = time.perf_counter()
        self.calls += 1
        try:
            msg = self.chat(self.masked(messages), tools)
        except Exception as e:                 # a model failure must not block: R27 is only ever an extra check
            self.errors += 1
            return {"match": False, "error": f"{type(e).__name__}: {e}"[:200]}
        finally:
            self.ms.append(round((time.perf_counter() - t0) * 1000, 1))
        proposed = [(self.name_map(n), a) for n, a in tool_calls(msg)]
        best = max((similarity(name, args, n, a) for n, a in proposed), default=0.0)
        match = best >= self.threshold and any(n == name for n, _ in proposed)
        self.matches += match
        return {"match": match, "score": round(best, 3), "masked_calls": [{"tool": n, "args": a} for n, a in proposed]}
