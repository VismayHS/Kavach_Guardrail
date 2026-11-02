"""How well the CPU injection classifier (C3) separates injected content from ordinary content, and what it costs.

    python -m bench.probe_eval          # writes bench/results/PROBE.md and probe.json

Texts come from three places, deduplicated:
  * our suite's environment: the injected emails and web pages (plain and obfuscated), injected SQL, vendor
    bank-change emails (social engineering rather than instructions to the AI), and the ordinary inbox, pages,
    files and CRM rows;
  * AgentDojo's banking environment: its ordinary bills, notices and transaction subjects;
  * AgentDojo's 'important_instructions' attack: the injected text for every banking user/injection task pair.
Nothing here was used to choose the model or its threshold (0.5, the model's own default).
"""
from __future__ import annotations

import json
import statistics
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench.suite import generate  # noqa: E402
from kavach.environment import Environment  # noqa: E402
from kavach.injection_probe import InjectionProbe  # noqa: E402

OUT = ROOT / "bench" / "results"


def corpus() -> list[tuple[str, str, int]]:
    """(category, text, label) with label 1 = injected instructions."""
    items: dict[str, tuple[str, int]] = {}

    def add(cat, text, label):
        text = str(text).strip()
        if text and text not in items:
            items[text] = (cat, label)

    env = Environment(tempfile.mkdtemp())
    for m in env.inbox:
        add("ours: injected email" if "AI ASSISTANT" in m["body"] else "ours: ordinary email", m["body"], int("AI ASSISTANT" in m["body"]))
    for url, page in env.web.items():
        add("ours: injected web page" if "assistant" in page else "ours: ordinary web page", page, int("assistant" in page))
    for name in ("notes.txt", "q3_summary.csv"):
        add("ours: workspace file", (env.workspace / name).read_text(), 0)
    for r in env.crm_query("SELECT * FROM customers LIMIT 15"):
        add("ours: CRM row", json.dumps(r), 0)
    for sc in generate(n_per_family=8, seed=11):
        for m in sc.inbox_extra:
            body = m["body"]
            if "bank details have changed" in body.lower():
                add("ours: bank-change email (social engineering)", body, 1)
            elif "please run:" in body.lower():
                add("ours: injected SQL in an email", body, 1)
            elif sc.injection:
                add("ours: injected email (incl. obfuscated)", body, 1)
            else:
                add("ours: ordinary email", body, 0)
        for page in sc.web_extra.values():
            add("ours: injected web page (incl. obfuscated)", page, 1)
    try:
        from agentdojo.attacks.attack_registry import load_attack
        from agentdojo.task_suite.load_suites import get_suite

        class _P:  # the attack reads the pipeline's name to address the model
            name = "meta-llama/Llama-3-70b-chat-hf"
        suite = get_suite("v1.2.2", "banking")
        env0 = suite.load_and_inject_default_environment({})
        for t in env0.bank_account.transactions:
            add("AgentDojo: ordinary transaction subject", t.subject, 0)
        for f, text in env0.filesystem.files.items():
            add("AgentDojo: ordinary file", text, 0)
        attack = load_attack("important_instructions", suite, _P())
        for ut in suite.user_tasks.values():
            for it in suite.injection_tasks.values():
                for text in attack.attack(ut, it).values():
                    add("AgentDojo: important_instructions attack", text, 1)
    except Exception as e:  # AgentDojo is optional
        print("AgentDojo texts skipped:", e)
    return [(cat, text, label) for text, (cat, label) in items.items()]


def evaluate(probe: InjectionProbe, items) -> dict:
    probe.latency_ms.clear()
    rows = []
    for cat, text, label in items:
        r = probe.scan(text)
        rows.append({"category": cat, "label": label, "flag": r["injection"], "score": r["score"], "ms": r["ms"]})
    by = defaultdict(list)
    for r in rows:
        by[r["category"]].append(r)
    pos, neg, ms = [r for r in rows if r["label"]], [r for r in rows if not r["label"]], [r["ms"] for r in rows]
    return {"detection_rate": sum(r["flag"] for r in pos) / max(1, len(pos)),
            "false_positive_rate": sum(r["flag"] for r in neg) / max(1, len(neg)),
            "latency_ms": {"p50": round(statistics.median(ms), 1), "p95": round(sorted(ms)[int(0.95 * (len(ms) - 1))], 1)},
            "per_category": {c: {"n": len(v), "label": v[0]["label"], "flagged": sum(r["flag"] for r in v)}
                             for c, v in sorted(by.items())}}


def main() -> dict:
    whole, seg = InjectionProbe(mode="whole"), InjectionProbe(mode="segments")
    if not whole.enabled:
        print("torch/transformers not installed: pip install torch transformers")
        return {}
    whole.scan("warm up")
    seg._pipe = whole._pipe                       # same model weights, two ways of reading the text
    items = corpus()
    out = {"model": whole.model_name, "threshold": whole.threshold, "n": len(items),
           "modes": {"whole": evaluate(whole, items), "segments": evaluate(seg, items)}}
    (OUT / "probe.json").write_text(json.dumps(out, indent=1))
    w, g = out["modes"]["whole"], out["modes"]["segments"]
    md = ["# Prompt-injection classifier on tool outputs (C3)", "",
          f"Model `{out['model']}` on CPU, threshold {out['threshold']} (the model's own default, not tuned). "
          f"{out['n']} distinct texts. Two ways of reading a text: **whole** (score it at once) and **segments** "
          "(score each sentence-level segment, take the max).", "",
          "| | Detection rate (injected) | False positives (ordinary) | p50 / p95 ms per text |", "|---|---|---|---|",
          f"| whole text | {w['detection_rate']:.1%} | {w['false_positive_rate']:.1%} | {w['latency_ms']['p50']} / {w['latency_ms']['p95']} |",
          f"| segments (KAVACH default) | {g['detection_rate']:.1%} | {g['false_positive_rate']:.1%} | {g['latency_ms']['p50']} / {g['latency_ms']['p95']} |",
          "", "**Caveat:** the segments mode was chosen after seeing the whole-text results on this same corpus, so its "
          "numbers are optimistic. They are reported next to the whole-text ones for that reason.", "",
          "| Source | Injected? | Texts | Flagged (whole) | Flagged (segments) |", "|---|---|---|---|---|"]
    for c, v in w["per_category"].items():
        sv = g["per_category"][c]
        md.append(f"| {c} | {'yes' if v['label'] else 'no'} | {v['n']} | {v['flagged']} ({v['flagged'] / v['n']:.0%}) | "
                  f"{sv['flagged']} ({sv['flagged'] / sv['n']:.0%}) |")
    md += ["", "What it is for: a flagged source loses reply-to-sender trust, and rule R29 sends state changes in that "
           "task to a human unless every target was typed by the user. It never blocks on its own, so a miss falls "
           "back to the provenance rules, and a false positive costs a human click, not a lost task.",
           "", "Injected SQL (\"Please run: UPDATE ...\") reads as an ordinary request from the email's author, not an "
           "instruction to an AI, and the classifier misses it; provenance catches it instead (R11: the statement was "
           "copied from untrusted content)."]
    (OUT / "PROBE.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    return out


if __name__ == "__main__":
    main()
