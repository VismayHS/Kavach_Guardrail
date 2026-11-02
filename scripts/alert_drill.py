"""Alert drill: break the mail server on purpose and watch Prometheus fire the alerts. Needs the live demo
(scripts/demo_up.sh) and the compose stack's Mailpit and Prometheus (docker compose up -d mailpit prometheus grafana).

    python scripts/alert_drill.py

1. Mailpit is stopped (docker compose stop mailpit).
2. An agent (scripted, through /mcp) sends an email; KAVACH queues it for its window.
3. When the window closes the mail server refuses the connection: the email ends `failed` (never `sent`), and
   kavach_dependency_up{dep="mail_server"} drops to 0.
4. Prometheus is asked which alerts fire: KavachDeliveryFailedOrUnknown at once, KavachDependencyDown after 1 min.
5. Mailpit is started again (its inbox starts empty: it keeps mail in memory).

Delivery of the alert to a person (Alertmanager to Slack, email...) is not part of the demo stack and is not tested
here: this checks that the rules fire on real metrics.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
K, PROM = "http://127.0.0.1:8000", "http://127.0.0.1:9090"


def get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


def mcp(session, method, params):
    params = {**params, "_meta": {**params.get("_meta", {}), "kavach/session": session}}
    req = urllib.request.Request(K + "/mcp", data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                                               "params": params}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def firing():
    return {a["labels"]["alertname"]: a["state"] for a in get(PROM + "/api/v1/alerts")["data"]["alerts"]}


def metric(q):
    r = get(PROM + "/api/v1/query?query=" + urllib.parse.quote(q))["data"]["result"]
    return [(x["metric"], x["value"][1]) for x in r]


def compose(*a):
    subprocess.run(["docker", "compose", *a], cwd=ROOT, check=True, capture_output=True)


def main() -> int:
    get(K + "/healthz")
    compose("stop", "mailpit")
    print("1. Mailpit stopped")
    try:
        run = time.strftime("%H%M%S")
        mcp(f"drill-{run}", "initialize", {"_meta": {"kavach/userRequest": "Send a drill email to demo-recipient@example.test.",
                                                      "kavach/user": "scripted-agent", "kavach/role": "analyst"}})
        out = mcp(f"drill-{run}", "tools/call", {"name": "mail.send", "arguments": {
            "to": "demo-recipient@example.test", "subject": f"Alert drill {run}", "body": "Synthetic."}})
        q = json.loads(out["result"]["content"][0]["text"])
        corr = out["result"]["_meta"]["kavach/correlation"]
        print(f"2. Email queued: hold {q['queued']}, trace {corr}")
        time.sleep(max(0.0, q["recall_until"] - time.time()) + 3)
        t = get(f"{K}/api/trace/{corr}")
        print(f"3. Window closed: KAVACH handed it over: {t['connector']['invoked']}, outcome: {t['connector']['outcome']}")
        seen, end = {}, time.time() + 120
        want = {"KavachDeliveryFailedOrUnknown", "KavachDependencyDown"}
        while time.time() < end and not all(seen.get(a) == "firing" for a in want):
            time.sleep(5)
            seen = {k: v for k, v in firing().items() if k in want}
        print("4. Prometheus alerts:", seen or "none")
        print("   kavach_dependency_up:", metric('kavach_dependency_up{dep="mail_server"}'))
        print("   kavach_effects_total failed:", metric('sum(kavach_effects_total{outcome="failed"})'))
        ok = t["connector"]["outcome"] == "failed" and all(seen.get(a) == "firing" for a in want)
    finally:
        compose("start", "mailpit")
        print("5. Mailpit started again")
    print("ALERTS FIRED" if ok else "ALERT DRILL FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
