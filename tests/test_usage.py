"""Model usage and cost by component: calls, retries and errors, tokens as the API's usage field reported them (a reply
without one is unknown, not zero), and an estimate from the versioned price table (a model it has no price for stays
unpriced: its tokens are counted, its cost is unknown)."""
from kavach import qualcomm
from kavach.usage import Usage, load_prices


def test_model_usage_is_what_the_api_said_and_cost_comes_from_the_price_table(monkeypatch):
    meter = Usage(load_prices())
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
    assert 'kavach_model_tokens_total{component="judge",model="Llama-3.3-70B",kind="prompt"} 1000' in text
    assert 'kavach_model_calls_total{component="explainer",model="Llama-3.1-8B",outcome="error"} 1' in text
    assert "kavach_model_cost_usd_total" in text and 'model="Llama-3.1-8B",prices=' not in text
