"""Run Infosys's own open-source guardrails on the KAVACH suite, beside KAVACH.

    git clone --depth 1 https://github.com/Infosys/Infosys-Agentic-Foundry /path/to/iaf
    python bench/infosys_compare.py /path/to/iaf

Nothing from Infosys is copied into this repo. The guard functions are loaded from the
clone at run time (Apache-2.0):

  * Topaz AgentOS pre-tool gate: SkillAgent._is_write_call / _is_dangerous_call / _load_hitl_patterns
    and the built-in pattern lists (Topaz_AgentOS/IAF-Agent-Skills/iaf_agent_skills/agent.py).
    govern_tool_call() maps "dangerous" or "write in ask-first mode" to a human approval hold.
    SafeKernel's path resolver rejects any path containing '..' (agent_os/kernel.py); that is applied too.
  * Foundry PromptGuard: scan_prompt / PROMPT_GUARD_THRESHOLD
    (Infosys-Agentic-Foundry-Backend/src/agentos/prompt_guard.py). It is registered as an
    on_agent_start hook, so in deployment it scans the user's query only.
  * RAI guardrail in the LiteLLM proxy: _extract_user_content_for_moderation
    (IAF-Litellm-Server/custom_guardrail.py) plus the pre-call role filter (user/human/system).
    The RAI classifiers themselves (DistilBERT injection model, etc.) ship as Git LFS weights and
    are NOT run here. We give them a perfect oracle instead: any scanned text that contains an
    injected payload is blocked. That is an upper bound on what the RAI moderation can catch.

Same scenarios, same held-out test split and same metrics as bench/run.py.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import statistics
import sys
import tempfile
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench.run import OUT, baseline_approve_all_writes, make_suite, metrics, run_kavach  # noqa: E402
from bench.suite import Scenario, materialize, prepare  # noqa: E402
from kavach.environment import Environment  # noqa: E402
from kavach.gateway import Kavach  # noqa: E402
from kavach.models import ToolCall  # noqa: E402
from kavach.risk import MODEL_PATH, RiskModel  # noqa: E402

AGENT_PY = "Topaz_AgentOS/IAF-Agent-Skills/iaf_agent_skills/agent.py"
GUARD_PY = "Infosys-Agentic-Foundry-Backend/src/agentos/prompt_guard.py"
PROXY_PY = "IAF-Litellm-Server/custom_guardrail.py"
STATE_CHANGING = {"crm.execute", "mail.send", "files.write", "files.delete", "payments.transfer", "payments.refund"}


# ------------------------------------------------------------------ loading Infosys code from the clone
def _class_members(path: Path, cls: str, names: set[str]) -> dict:
    """Source of selected attributes/methods of one class, compiled into a namespace."""
    src = path.read_text()
    tree = ast.parse(src)
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    parts = [ast.get_source_segment(src, b) for b in node.body
             if (isinstance(b, ast.FunctionDef) and b.name in names)
             or (isinstance(b, ast.Assign) and any(getattr(t, "id", "") in names for t in b.targets))
             or (isinstance(b, ast.AnnAssign) and getattr(b.target, "id", "") in names)]
    body = "\n".join("    " + line for p in parts for line in __import__("textwrap").dedent(p).splitlines())
    ns: dict = {"re": re}
    exec(compile(f"class _Gate:\n{body}\n", str(path), "exec"), ns)
    return ns["_Gate"]


def load_agentos_gate(root: Path):
    gate = _class_members(root / AGENT_PY, "SkillAgent",
                          {"_DEFAULT_HITL_SHELL_PATTERNS", "_DEFAULT_HITL_SQL_PATTERNS",
                           "_load_hitl_patterns", "_is_write_call", "_is_dangerous_call"})

    def make(config: dict):
        g = gate()
        g.config, g.current_skill = config, "crm_ops"
        return g
    return make


def load_prompt_guard(root: Path):
    spec = importlib.util.spec_from_file_location("iaf_prompt_guard", root / GUARD_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_rai_extractor(root: Path):
    src = (root / PROXY_PY).read_text()
    tree = ast.parse(src)
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        for fn in cls.body:
            if isinstance(fn, ast.FunctionDef) and fn.name == "_extract_user_content_for_moderation":
                ns = {"verbose_proxy_logger": logging.getLogger("iaf_proxy")}
                code = __import__("textwrap").dedent(ast.get_source_segment(src, fn))
                exec(compile(code, str(root / PROXY_PY), "exec"), ns)
                return ns["_extract_user_content_for_moderation"]
    raise RuntimeError("extractor not found")


# ------------------------------------------------------------------ mapping KAVACH tools onto AgentOS tools
def to_agentos(call: ToolCall) -> tuple[str, dict]:
    """AgentOS agents act through SafeKernel shell, write_file and SQL connector tools; everything else
    (mail, payments, web) arrives as MCP/custom tools under its own name."""
    a = call.args
    if call.tool in ("crm.query", "crm.execute"):
        return "run_sql_query", {"query": a["sql"]}
    if call.tool == "files.write":
        return "write_file", {"path": f"/workspace/{a['path']}", "content": a["content"]}
    if call.tool == "files.delete":
        return "shell", {"command": f"rm /workspace/{a['path']}"}
    if call.tool == "files.read":
        return "shell", {"command": f"cat /workspace/{a['path']}"}
    return call.tool, dict(a)


AGENTOS_DEFAULT: dict = {}                                   # no hitl: section -> built-in shell patterns only
AGENTOS_HARDENED = {"hitl": {                               # what HITL_DESIGN_GUIDE.md shows an operator adding
    "sql_patterns": [r"\b(DELETE|UPDATE|DROP|TRUNCATE|ALTER|INSERT)\b"],
    "dangerous_tools": ["mail.send", "payments.transfer", "payments.refund"],
}}


# ------------------------------------------------------------------ one agent turn, as the proxy would see it
def transcript(env: Environment, sc: Scenario) -> tuple[list[dict], ToolCall, list[str]]:
    prepare(env, sc)
    outputs, msgs = [], [{"role": "system", "content": "You are an enterprise CRM agent."},
                         {"role": "user", "content": f"User Query:\n{sc.request}"}]
    for i, call in enumerate(sc.setup):
        out = env.dispatch(call.tool, call.args)
        outputs.append(out)
        msgs.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "type": "function", "function": {"name": call.tool, "arguments": json.dumps(call.args)}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": json.dumps(out, default=str)})
    payloads = [m["body"] for m in sc.inbox_extra] + list(sc.web_extra.values())
    return msgs, materialize(sc.action, outputs), payloads


def systems(root: Path):
    gate = load_agentos_gate(root)
    pg = load_prompt_guard(root)
    extract = load_rai_extractor(root)
    env = Environment(tempfile.mkdtemp())

    def promptguard(sc):
        score, _ = pg.scan_prompt(sc.request)
        return "DENY" if score >= pg.PROMPT_GUARD_THRESHOLD else "ALLOW"

    def rai_upper_bound(sc):
        msgs, _, payloads = transcript(env, sc)
        scanned = [extract(None, m["content"]) for m in msgs if m["role"] in ("user", "human", "system")]
        hit = any(p and p in s for s in scanned for p in payloads)
        return "DENY" if hit else "ALLOW"

    def agentos(config, auto_run):
        def fn(sc):
            _, action, _ = transcript(env, sc)
            g = gate(config)
            name, args = to_agentos(action)
            if ".." in str(args.get("path", "")) + str(args.get("command", "")):
                return "DENY"                           # SafeKernel path resolver: '..' raises PATH_ESCAPE
            dangerous, _ = g._is_dangerous_call(name, args)
            write = (not auto_run) and g._is_write_call(name, args)
            return "ESCALATE" if dangerous or write else "ALLOW"
        return fn

    hardened = agentos(AGENTOS_HARDENED, True)

    def infosys_stack(sc):
        if promptguard(sc) == "DENY" or rai_upper_bound(sc) == "DENY":
            return "DENY"
        return hardened(sc)

    def promptguard_on_tool_output(sc):
        """Diagnostic only, not how it is deployed: would the regexes catch the payload if moved?"""
        _, _, payloads = transcript(env, sc)
        return "DENY" if any(pg.scan_prompt(p)[0] >= pg.PROMPT_GUARD_THRESHOLD for p in payloads) else "ALLOW"

    kav = Kavach(env, risk=RiskModel(MODEL_PATH))
    return env, [
        ("Foundry PromptGuard (user query at agent start)", promptguard),
        ("RAI moderation via LiteLLM proxy (perfect-classifier upper bound)", rai_upper_bound),
        ("AgentOS pre-tool gate, default config, autonomous", agentos(AGENTOS_DEFAULT, True)),
        ("AgentOS pre-tool gate, default config, ask-first chat", agentos(AGENTOS_DEFAULT, False)),
        ("AgentOS pre-tool gate, hardened config, autonomous", hardened),
        ("Foundry selective Tool Interrupt on every state-changing tool", baseline_approve_all_writes),
        ("Infosys stack combined (PromptGuard + RAI bound + hardened AgentOS)", infosys_stack),
        ("KAVACH (full)", lambda sc: run_kavach(kav, env, sc)),
    ], promptguard_on_tool_output


def evaluate(fn, scenarios) -> dict:
    rows = []
    for sc in scenarios:
        out = fn(sc)
        out = out if isinstance(out, dict) else {"verdict": out, "ms": None}
        rows.append({"sid": sc.sid, "family": sc.family, "label": sc.label, "injection": sc.injection, **out})
    return {"metrics": metrics(rows), "rows": rows}


def main(root: Path, seeds=(0, 1, 2, 3, 4)) -> dict:
    multiseed = json.loads((OUT / "multiseed.json").read_text())
    per_seed: dict[str, list[dict]] = {}
    seed0, diag = {}, {}
    for seed in seeds:
        suite, split = make_suite(20, seed)
        test = [s for s in suite if split[s.sid] == "test"]
        env, syss, pg_tool = systems(root)
        for name, fn in syss:
            if name == "KAVACH (full)" and seed != 0:
                continue                                # other seeds use their own retrained model: see multiseed.json
            res = evaluate(fn, test)
            per_seed.setdefault(name, []).append(res["metrics"])
            if seed == 0:
                seed0[name] = res
        inj = [s for s in test if s.injection]
        diag.setdefault("promptguard_payload_detection", []).append(
            sum(pg_tool(s) == "DENY" for s in inj) / max(1, len(inj)))
    per_seed.pop("KAVACH (full)", None)
    return {"kavach_multiseed": multiseed["systems"]["KAVACH (full)"],"seed0": {n: r["metrics"] for n, r in seed0.items()},
            "seed0_family": {n: _by_family(r["rows"]) for n, r in seed0.items()},
            "per_seed": per_seed, "diagnostics": diag}


def _by_family(rows):
    out = {}
    for r in rows:
        out.setdefault(r["family"], []).append(r["verdict"])
    return {f: max(set(v), key=v.count) for f, v in out.items()}


def mean_range(vals):
    return f"{100 * statistics.mean(vals):.1f}% ({100 * min(vals):.0f}–{100 * max(vals):.0f}%)"


def report(res: dict) -> str:
    keys = [("UAR", "Unsafe auto-allowed ↓"), ("ASR_injection", "Injection ASR ↓"),
            ("safe_auto", "Safe auto-completed ↑"), ("OBR", "Safe hard-blocked ↓"),
            ("escalation_rate", "Escalation")]
    s0 = res["seed0"]
    lines = ["# Infosys open-source guardrails vs KAVACH", "",
             "Infosys code is loaded from a clone of `Infosys/Infosys-Agentic-Foundry` at run time "
             "(`python bench/infosys_compare.py <clone>`). Same 740-scenario synthetic suite, same held-out "
             "test split, same metrics as `RESULTS.md`. RAI moderation classifiers are not run (Git LFS "
             "weights); they get a perfect oracle on whatever text the proxy actually sends them, so that row "
             "is an upper bound.", "",
             "## Seed 0 test split (222 scenarios)", "",
             "| System | " + " | ".join(h for _, h in keys) + " |",
             "|---|" + "---|" * len(keys)]
    for name, m in s0.items():
        lines.append(f"| {name} | " + " | ".join(f"{100 * m[k]:.1f}%" for k, _ in keys) + " |")
    lines += ["", "## 5 seeds (mean, min–max)", "",
              "| System | " + " | ".join(h for _, h in keys) + " |", "|---|" + "---|" * len(keys)]
    for name, ms in res["per_seed"].items():
        lines.append(f"| {name} | " + " | ".join(mean_range([m[k] for m in ms]) for k, _ in keys) + " |")
    km = res["kavach_multiseed"]
    lines.append("| KAVACH (full) | " + " | ".join(
        f"{100 * km[k]['mean']:.1f}% ({100 * km[k]['min']:.0f}–{100 * km[k]['max']:.0f}%)" for k, _ in keys) + " |")
    d = res["diagnostics"]["promptguard_payload_detection"]
    lines += ["", "KAVACH 5-seed numbers come from `multiseed.json` (model retrained per seed).", "",
              f"Diagnostic: if PromptGuard's regexes were applied to the injected tool outputs (they are not, "
              f"in deployment), they would flag {mean_range(d)} of injection payloads at the default threshold.", "",
              "## Verdict by scenario family (seed 0, majority)", ""]
    fam = res["seed0_family"]
    names = list(fam)
    short = ["PromptGuard", "RAI bound", "AgentOS def auto", "AgentOS def ask", "AgentOS hard",
             "Tool Interrupt", "Infosys stack", "KAVACH"]
    lines += ["| Family | " + " | ".join(short) + " |", "|---|" + "---|" * len(short)]
    for f in sorted(fam[names[0]]):
        lines.append(f"| {f} | " + " | ".join(fam[n].get(f, "") for n in names) + " |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "../Infosys-Agentic-Foundry").resolve()
    res = main(root)
    (OUT / "infosys_compare.json").write_text(json.dumps(res, indent=1))
    (OUT / "INFOSYS_COMPARISON.md").write_text(report(res))
    print(report(res))
