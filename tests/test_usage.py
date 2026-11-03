"""Model usage and cost by component: calls, retries and errors, tokens as the API's usage field reported them (a reply
without one is unknown, not zero), and an estimate from the versioned price table (a model it has no price for stays
unpriced: its tokens are counted, its cost is unknown)."""
from kavach import qualcomm
from kavach.usage import Usage, load_prices


def test_model_usage_is_what_the_api_said_and_cost_comes_from_the_price_table(monkeypatch):
    table = load_prices()
    table = {**table, "models": {"Llama-3.3-70B": table["models"]["Llama-3.3-70B"]}}   # 8B left out: unpriced
    meter = Usage(table)
    monkeypatch.setattr("kavach.usage.METER", meter)
    replies = iter([{"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 1000, "completion_tokens": 200}},
                    {"choices": [{"message": {"content": "ok"}}]}])
    monkeypatch.setattr(qualcomm.QualcommCloudAI, "_post", lambda self, path, body: next(replies))
    llm = qualcomm.QualcommCloudAI(endpoint="https://example.test/v2", api_key="x", model="Llama-3.3-70B",
                                   component="judge")
    llm.chat([{"role": "user", "content": "hi"}])
    llm.chat([{"role": "user", "content": "hi"}])                          # no usage field: unknown, not zero

    def boom(self, path, body):
        raise TimeoutError("down")
    monkeypatch.setattr(qualcomm.QualcommCloudAI, "_post", boom)
    other = qualcomm.QualcommCloudAI(endpoint="https://example.test/v2", api_key="x", model="Llama-3.1-8B",
                                     component="explainer")
    try:
        other.chat([{"role": "user", "content": "hi"}])
    except TimeoutError:
        pass
    s = meter.snapshot()
    judge = next(r for r in s["rows"] if r["component"] == "judge")
    assert (judge["calls"], judge["prompt_tokens"], judge["completion_tokens"], judge["usage_unknown"]) == (2, 1000, 200, 1)
    price = load_prices()["models"]["Llama-3.3-70B"]
    assert abs(s["estimated_cost_usd"] - (1000 * price["input"] + 200 * price["output"]) / 1e6) < 1e-9
    expl = next(r for r in s["rows"] if r["component"] == "explainer")
    assert expl["errors"] == 1 and not expl["priced"] and s["price_table"] == load_prices()["version"]
    text = "\n".join(meter.metrics())
    assert 'kavach_model_tokens_total{component="judge",side="kavach",model="Llama-3.3-70B",kind="prompt"} 1000' in text
    assert 'kavach_model_calls_total{component="explainer",side="kavach",model="Llama-3.1-8B",outcome="error"} 1' in text
    assert "kavach_model_cost_usd_total" in text and 'model="Llama-3.1-8B",prices=' not in text


def test_every_model_kavach_uses_has_a_reference_price_with_its_source():
    t = load_prices()
    for m in ("Llama-3.1-8B", "Llama-3.3-70B"):
        row = t["models"][m]
        assert row["input"] > 0 and row["output"] > 0 and row["qualcomm"] is False and "reference" in row["source"]


def test_kavach_overhead_and_agent_spend_are_told_apart_and_cents_are_not_rounded_away():
    from kavach.usage import side_of
    meter = Usage({"version": "t", "models": {"m": {"input": 0.05, "output": 0.08}}})
    meter.record("judge", "m", {"prompt_tokens": 7, "completion_tokens": 1}, ok=True)     # 4.3e-07 USD
    meter.record("agent", "m", {"prompt_tokens": 1000, "completion_tokens": 100}, ok=True)
    s = meter.snapshot()
    assert abs(s["kavach_cost_usd"] - 4.3e-07) < 1e-15 and abs(s["agent_cost_usd"] - 5.8e-05) < 1e-15
    text = "\n".join(meter.metrics())
    line = next(x for x in text.splitlines() if x.startswith('kavach_model_cost_usd_total{component="judge"'))
    assert 'side="kavach"' in line and abs(float(line.split()[-1]) - 4.3e-07) < 1e-15 and "0.000000" not in line
    assert side_of("redteam-attacker") == "agent" and side_of("explainer") == "kavach"
