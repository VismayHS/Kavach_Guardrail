"""Ground-truth replay on AgentDojo: KAVACH against the right calls, and against an obedient agent (offline, no model).

    python -m bench.agentdojo_replay                    # banking and slack -> bench/results/AGENTDOJO_REPLAY.md
    python -m bench.agentdojo_replay --suite slack

AgentDojo ships, for every task, the calls a correct agent makes (`ground_truth`). Two questions need no model:

* Benign: the agent makes exactly the user task's calls. Does KAVACH let the task get done (AgentDojo's own utility
  check, with KAVACH in the loop)? A task it breaks here is a false positive that no model can avoid. ESCALATE is
  kept apart from DENY: in production a person approves it, in the benchmark it counts as a block.
* Attacked: the environment carries the attack's text (AgentDojo's important_instructions, the attack the live runs
  use) and the agent is obedient: it does the user's task, then exactly the attacker's calls. Is the attacker's goal
  done afterwards (AgentDojo's own security check)? Worst case for the model, best case for the attacker; a live
  model obeys less often. When KAVACH stopped the read that would have shown the attack, the agent never saw it;
  that is listed apart, because it also costs the user's task.

This checks KAVACH's rules and manifests, not an agent: the live runs (bench/agentdojo_kavach.py) also depend on what
the model does. A replay takes seconds.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agentdojo.agent_pipeline import AgentPipeline, InitQuery, SystemMessage, ToolsExecutionLoop, ToolsExecutor  # noqa: E402
from agentdojo.agent_pipeline.agent_pipeline import load_system_message  # noqa: E402
from agentdojo.agent_pipeline.base_pipeline_element import BasePipelineElement  # noqa: E402
from agentdojo.attacks.attack_registry import load_attack  # noqa: E402
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime  # noqa: E402
from agentdojo.task_suite.task_suite import functions_stack_trace_from_messages, model_output_from_messages  # noqa: E402
from agentdojo.models import MODEL_NAMES  # noqa: E402
from agentdojo.types import ChatAssistantMessage, get_text_content_as_str, text_content_block_from_string  # noqa: E402

from bench.agentdojo_kavach import KavachToolsExecutor, _commit, _suite, kavach_config  # noqa: E402

OUT = ROOT / "bench" / "results"
AGENT = "qualcomm-Llama-3.3-70B"     # the live runs' agent name: the attack addresses the model by it


class Script(BasePipelineElement):
    """Plays a fixed list of calls, one per turn, then the task's expected answer."""

    def __init__(self, calls: list[FunctionCall], answer: str):
        self.calls, self.answer, self.n, self.messages = list(calls), answer, 0, []
        self.name = f"{AGENT}-replay"

    def query(self, query, runtime, env=None, messages=(), extra_args={}):  # noqa: B006
        self.messages = list(messages)
        if self.calls:
            c = self.calls.pop(0)
            self.n += 1
            out = ChatAssistantMessage(role="assistant", content=None, tool_calls=[
                FunctionCall(function=c.function, args=dict(c.args), id=f"gt{self.n}")])
        else:
            out = ChatAssistantMessage(role="assistant", content=[text_content_block_from_string(self.answer)],
                                       tool_calls=None)
        return query, runtime, env, [*messages, out], extra_args


def _play(suite, user_task, injection_task, injections: dict, defense: str) -> dict:
    """One run, as AgentDojo's run_task_with_pipeline does it, with the scripted agent and KAVACH in the loop."""
    env = user_task.init_environment(suite.load_and_inject_default_environment(injections))
    pre = env.model_copy(deep=True)
    calls = list(user_task.ground_truth(pre.model_copy(deep=True)))
    n_user = len(calls)
    if injection_task is not None:
        calls += list(injection_task.ground_truth(pre.model_copy(deep=True)))
    script = Script(calls, getattr(user_task, "GROUND_TRUTH_OUTPUT", "") or "Done.")
    kav = KavachToolsExecutor(suite, kavach_config(defense)) if defense != "none" else None
    loop = ToolsExecutionLoop([kav or ToolsExecutor(), script], max_iters=len(calls) + 5)
    pipe = AgentPipeline([SystemMessage(load_system_message(None)), InitQuery(), script, loop])
    pipe.name = script.name
    _, _, env, messages, _ = pipe.query(user_task.PROMPT, FunctionsRuntime(suite.tools), env)
    output = model_output_from_messages(messages) or []
    traces = functions_stack_trace_from_messages(messages)
    utility = suite._check_task_result(user_task, output, pre, env, traces)
    attack = executed = None
    if injection_task is not None:
        attack = suite._check_task_result(injection_task, output, pre, env, traces)
        # some checks read the calls the agent *attempted* (slack injection_task_5): KAVACH's blocks still count
        # there, so the same check is also run on the calls that actually executed
        executed = suite._check_task_result(injection_task, output, pre, env, executed_calls(messages))
    decisions = kav.decisions if kav else []
    for i, d in enumerate(decisions):
        d["part"] = "user" if i < n_user else "attacker"
    seen = injection_task is None or any(
        m.get("role") == "tool" and m.get("content") and injection_task.GOAL in get_text_content_as_str(m["content"])
        for m in messages)
    return {"utility": bool(utility), "attack": None if attack is None else bool(attack),
            "attack_executed": None if executed is None else bool(executed), "seen": seen,
            "decisions": [{k: d[k] for k in ("part", "tool", "verdict", "reason")} for d in decisions]}


def executed_calls(messages) -> list[FunctionCall]:
    """The calls whose tool result is not a KAVACH block."""
    blocked = {m.get("tool_call_id") for m in messages if m.get("role") == "tool"
               and str(m.get("error") or "").startswith("BLOCKED by KAVACH")}
    return [c for c in functions_stack_trace_from_messages(messages) if c.id not in blocked]


def replay(suite_name: str = "banking", defense: str = "kavach", user_tasks: list[str] | None = None,
           injection_tasks: list[str] | None = None) -> dict:
    suite = _suite(suite_name)
    MODEL_NAMES.setdefault(AGENT, "AI assistant")
    attack = load_attack("important_instructions", suite, Script([], ""))
    users = {k: v for k, v in suite.user_tasks.items() if user_tasks is None or k in user_tasks}
    injs = {k: v for k, v in suite.injection_tasks.items() if injection_tasks is None or k in injection_tasks}
    benign, attacked = {}, {}
    for uid, ut in users.items():
        gt = _play(suite, ut, None, {}, "none")             # AgentDojo's check on its own ground truth, no defense
        r = _play(suite, ut, None, {}, defense)
        benign[uid] = {**r, "ground_truth_utility": gt["utility"]}
        for iid, it in injs.items():
            inj = attack.attack(ut, it)
            undefended = _play(suite, ut, it, inj, "none")
            attacked[f"{uid}|{iid}"] = {**_play(suite, ut, it, inj, defense), "undefended": undefended["attack"]}
    valid = [k for k, v in benign.items() if v["ground_truth_utility"]]
    blocked = {k: [d for d in benign[k]["decisions"] if d["verdict"] in ("DENY", "ESCALATE")] for k in valid}
    seen = [v for v in attacked.values() if v["seen"]]
    return {"suite": suite_name, "defense": defense, "kavach_commit": _commit(), "attack": "important_instructions",
            "benign_tasks": len(valid), "benign_done": sum(benign[k]["utility"] for k in valid),
            "benign_escalated_only": sum(1 for k in valid if not benign[k]["utility"] and blocked[k]
                                         and all(d["verdict"] == "ESCALATE" for d in blocked[k])),
            "attacked": len(attacked), "undefended_success": sum(v["undefended"] for v in attacked.values()),
            # an attack the agent never saw can't be obeyed (KAVACH stopped the read that would have shown it)
            "attack_not_seen": len(attacked) - len(seen),
            "attack_success": sum(v["attack"] for v in seen),
            "attack_success_executed": sum(v["attack_executed"] for v in seen),
            "utility_under_attack": sum(v["utility"] for v in attacked.values()),
            "blocking_rules": dict(Counter(d["reason"][1:d["reason"].index("]")]
                                           for v in attacked.values() for d in v["decisions"]
                                           if d["part"] == "attacker" and d["verdict"] in ("DENY", "ESCALATE")
                                           and d["reason"].startswith("["))),
            "benign": benign, "attacked_runs": attacked}


def write(results: list[dict]) -> str:
    md = ["# AgentDojo ground-truth replay (offline, no model)", "",
          "AgentDojo ships the calls a correct agent makes for every task. They are replayed through KAVACH:", "",
          "- **Benign**: the agent makes exactly the user task's calls; AgentDojo's own check says whether the task "
          "got done with KAVACH in the loop. A task stopped here is a false positive no model can avoid. In "
          "production an ESCALATE goes to a person; here, as in the benchmark, it counts as a block.",
          "- **Obedient agent under attack**: the attack text (important_instructions, as in the live runs) is in "
          "the data; the agent does the user's task, then exactly the attacker's calls. AgentDojo's own check says "
          "whether the attacker's goal got done. A live model obeys less often: this is the attacker's best case. "
          "When KAVACH stopped the read that carries the attack, the agent never saw it and can't obey it.",
          "", "| Suite | Benign tasks done | Stopped only by ESCALATE | Attacks, undefended | Attacks with KAVACH ↓ "
          "| … counting only calls that ran | Attack never reached the agent | User task done under attack |",
          "|---|---|---|---|---|---|---|---|"]
    for r in results:
        n = r["attacked"]
        md.append(f"| {r['suite']} | {r['benign_done']}/{r['benign_tasks']} | {r['benign_escalated_only']} | "
                  f"{r['undefended_success']}/{n} | {r['attack_success']}/{n} | {r['attack_success_executed']}/{n} | "
                  f"{r['attack_not_seen']} | {r['utility_under_attack']}/{n} |")
    md += ["", "AgentDojo checks one slack attack (injection_task_5: invite Fred, add him to #general, remove him) "
           "from the calls the agent *attempted*, so a call KAVACH blocked still counts as the attacker's. The "
           "column 'counting only calls that ran' applies the same check to the calls that executed."]
    for r in results:
        md += ["", f"## {r['suite']}", "", f"Rules that stopped the attacker's calls: {r['blocking_rules']}", ""]
        stopped = {k: v for k, v in r["benign"].items() if v["ground_truth_utility"] and not v["utility"]}
        if stopped:
            md += ["Benign tasks KAVACH stopped (the first call it stopped):", "", "| Task | Call | Verdict | Why |",
                   "|---|---|---|---|"]
            for k, v in stopped.items():
                d = next((d for d in v["decisions"] if d["verdict"] in ("DENY", "ESCALATE")), None)
                why = (d["reason"] if d else "every call allowed; the answer check failed").replace("|", "/")
                md.append(f"| {k} | {d['tool'] if d else '-'} | {d['verdict'] if d else '-'} | {why[:170]} |")
        won = {k: v for k, v in r["attacked_runs"].items() if v["attack"] and v["seen"]}
        if won:
            md += ["", "Obedient-agent attacks that succeeded:", "", "| User task / attack | Attacker's calls KAVACH "
                   "let through | Counting only calls that ran |", "|---|---|---|"]
            for k, v in won.items():
                let = [d["tool"] for d in v["decisions"] if d["part"] == "attacker"
                       and d["verdict"] in ("ALLOW", "ALLOW_WITH_SAFEGUARD")]
                md.append(f"| {k} | {', '.join(let) or '-'} | {'succeeded' if v['attack_executed'] else 'failed'} |")
    md += ["", f"KAVACH commit `{results[0]['kavach_commit']}`; rules, risk model and operating point as shipped "
           "(LLM judge off, as in the live runs). Regenerate: `python -m bench.agentdojo_replay`."]
    text = "\n".join(md) + "\n"
    (OUT / "AGENTDOJO_REPLAY.md").write_text(text)
    return text


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--suite", action="append", help="banking, slack (default: both)")
    ap.add_argument("--defense", default="kavach", choices=["kavach", "kavach_rules"])
    a = ap.parse_args(argv)
    results = [replay(s, a.defense) for s in (a.suite or ["banking", "slack"])]
    for r in results:
        (OUT / f"agentdojo_replay_{r['suite']}.json").write_text(json.dumps(r, indent=1, default=str))
    print(write(results))


if __name__ == "__main__":
    main()
