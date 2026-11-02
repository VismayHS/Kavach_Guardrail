"""Model usage and estimated cost, by component (judge, explainer, planner, agent, red team...).

Every Qualcomm call goes through QualcommCloudAI.chat, which reports here: the call, whether it succeeded, how many
retries it took (rate limits, 5xx, timeouts), and the token counts from the response's own `usage` field. Usage is
what the API said; a reply without a usage field is counted as unknown, never as zero. Cost is an estimate: tokens
times the versioned price table (kavach/model_prices.json, or KAVACH_PRICE_TABLE); a model with no price stays
unpriced. Served at GET /metrics (kavach_model_*) and GET /api/usage.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

PRICES = Path(os.environ.get("KAVACH_PRICE_TABLE") or Path(__file__).with_name("model_prices.json"))


def load_prices(path: Path | None = None) -> dict:
    try:
        return json.loads(Path(path or PRICES).read_text())
    except (OSError, ValueError):
        return {"version": "none", "models": {}}


class Usage:
    def __init__(self, prices: dict | None = None):
        self.lock = threading.Lock()
        self.prices = prices or load_prices()
        self.rows: dict[tuple[str, str], dict] = {}

    def _row(self, component: str, model: str) -> dict:
        return self.rows.setdefault((component, model), {
            "calls": 0, "errors": 0, "retries": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "usage_unknown": 0, "cost_usd": 0.0, "priced": model in self.prices.get("models", {})})

    def record(self, component: str, model: str, usage: dict | None, ok: bool, retries: int = 0) -> None:
        with self.lock:
            r = self._row(component or "model", model or "?")
            r["calls"] += 1
            r["retries"] += max(0, retries)
            if not ok:
                r["errors"] += 1
                return
            p, c = (usage or {}).get("prompt_tokens"), (usage or {}).get("completion_tokens")
            if not isinstance(p, (int, float)) or not isinstance(c, (int, float)):
                r["usage_unknown"] += 1
                return
            r["prompt_tokens"] += int(p)
            r["completion_tokens"] += int(c)
            price = self.prices.get("models", {}).get(model)
            if price:
                r["cost_usd"] += (p * price["input"] + c * price["output"]) / 1e6

    def snapshot(self) -> dict:
        with self.lock:
            rows = [{"component": k[0], "model": k[1], **v} for k, v in sorted(self.rows.items())]
        priced = [r for r in rows if r["priced"]]
        return {"price_table": self.prices.get("version"), "currency": self.prices.get("currency", "USD"),
                "note": self.prices.get("note"), "rows": rows,
                "calls": sum(r["calls"] for r in rows), "errors": sum(r["errors"] for r in rows),
                "tokens": sum(r["prompt_tokens"] + r["completion_tokens"] for r in rows),
                "usage_unknown_calls": sum(r["usage_unknown"] for r in rows),
                "estimated_cost_usd": round(sum(r["cost_usd"] for r in priced), 6),
                "unpriced_tokens": sum(r["prompt_tokens"] + r["completion_tokens"] for r in rows if not r["priced"])}

    def metrics(self) -> list[str]:
        """Prometheus lines. Labels are the component and the model name only (a handful of values each)."""
        with self.lock:
            rows = sorted(self.rows.items())
        ver = self.prices.get("version", "none")
        out = ["# HELP kavach_model_calls_total Calls to a model, by component and outcome.",
               "# TYPE kavach_model_calls_total counter"]
        for (comp, model), r in rows:
            out.append(f'kavach_model_calls_total{{component="{comp}",model="{model}",outcome="ok"}} {r["calls"] - r["errors"]}')
            out.append(f'kavach_model_calls_total{{component="{comp}",model="{model}",outcome="error"}} {r["errors"]}')
        out += ["# HELP kavach_model_retries_total Retries (rate limits, server errors, timeouts) inside those calls.",
                "# TYPE kavach_model_retries_total counter"]
        out += [f'kavach_model_retries_total{{component="{c}",model="{m}"}} {r["retries"]}' for (c, m), r in rows]
        out += ["# HELP kavach_model_tokens_total Tokens, as the API's usage field reported them.",
                "# TYPE kavach_model_tokens_total counter"]
        for (comp, model), r in rows:
            out.append(f'kavach_model_tokens_total{{component="{comp}",model="{model}",kind="prompt"}} {r["prompt_tokens"]}')
            out.append(f'kavach_model_tokens_total{{component="{comp}",model="{model}",kind="completion"}} {r["completion_tokens"]}')
        out += ["# HELP kavach_model_usage_unknown_total Successful calls whose reply carried no usage field.",
                "# TYPE kavach_model_usage_unknown_total counter"]
        out += [f'kavach_model_usage_unknown_total{{component="{c}",model="{m}"}} {r["usage_unknown"]}' for (c, m), r in rows]
        out += [f"# HELP kavach_model_cost_usd_total Estimated cost: tokens x price table {ver} (priced models only).",
                "# TYPE kavach_model_cost_usd_total counter"]
        out += [f'kavach_model_cost_usd_total{{component="{c}",model="{m}",prices="{ver}"}} {r["cost_usd"]:.6f}'
                for (c, m), r in rows if r["priced"]]
        out += ["# HELP kavach_model_unpriced_tokens_total Tokens of models the price table has no price for.",
                "# TYPE kavach_model_unpriced_tokens_total counter"]
        out += [f'kavach_model_unpriced_tokens_total{{component="{c}",model="{m}"}} '
                f'{r["prompt_tokens"] + r["completion_tokens"]}' for (c, m), r in rows if not r["priced"]]
        return out


METER = Usage()
