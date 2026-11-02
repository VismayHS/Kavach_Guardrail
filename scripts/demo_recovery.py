"""Recovery, live: cancel before delivery survives a crash. Against the running demo (scripts/demo_up.sh):

    python scripts/demo_recovery.py              # cancel, crash, restart: still cancelled
    python scripts/demo_recovery.py kill-switch  # crash, restart, pause: the waiting email never leaves

1. An agent (scripted, through the same /mcp door Claude uses) queues two emails to demo-recipient@example.test.
2. A person cancels the first one.
3. KAVACH is killed (kill -9, no clean shutdown) while the second one is still waiting, and started again.
4. After both windows have passed, the real inbox (Mailpit) and the receipts are checked: the cancelled email never
   arrived, the other arrived exactly once, and the receipt chain still verifies.

Nothing here is simulated: the process really dies, the inbox is Mailpit's, and the state comes back from the
database (.kavach/demo.db). Each email's X-Kavach-Correlation header names its trace (GET /api/trace/<id>).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
K = os.environ.get("KAVACH_URL", "http://127.0.0.1:8000")
MP = os.environ.get("MAILPIT_URL", "http://127.0.0.1:8025")
TO = "demo-recipient@example.test"


def call(method, path, body=None):
    req = urllib.request.Request(K + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or b"null")


def rpc(session, method, params):
    params = {**params, "_meta": {**params.get("_meta", {}), "kavach/session": session}}
    return call("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def inbox(subject):
    q = urllib.parse.quote(f'subject:"{subject}"')
    with urllib.request.urlopen(f"{MP}/api/v1/search?query={q}", timeout=5) as r:
        return json.loads(r.read())["messages_count"]


def ready(timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        try:
            return call("GET", "/readyz")
        except Exception:
            time.sleep(0.5)
    raise SystemExit("KAVACH did not come back; see .kavach/recovery.log")


def check(ok, text):
    print(f"  {'PASS' if ok else 'FAIL'}  {text}")
    return ok


def main() -> int:
    pidfile = ROOT / ".kavach" / "kavach.pid"
    try:
        ready(3)
    except SystemExit:
        print("Start the demo first: scripts/demo_up.sh")
        return 1
    if not pidfile.exists():
        print("This needs the KAVACH that scripts/demo_up.sh started (it kills and restarts it).")
        return 1
    run = time.strftime("%H%M%S")
    session = f"recovery-{run}"
    rpc(session, "initialize", {"_meta": {"kavach/userRequest": f"Send two recovery-test emails to {TO}.",
                                          "kavach/user": "scripted-agent", "kavach/role": "analyst"}})
    sent = {}
    for name in ("cancel me", "let me go"):
        subject = f"Recovery test {run}: {name}"
        out = rpc(session, "tools/call", {"name": "mail.send", "arguments": {"to": TO, "subject": subject,
                                                                            "body": "Synthetic test email."}})
        meta = out["result"]["_meta"]
        sent[name] = {"subject": subject, "receipt": meta["kavach/receipt"], "corr": meta["kavach/correlation"],
                      "text": json.loads(out["result"]["content"][0]["text"])}
        print(f"1. Queued '{subject}': {meta['kavach/verdict']}, hold {sent[name]['text'].get('queued')}, "
              f"trace {meta['kavach/correlation']}")
    due = max(v["text"].get("recall_until", time.time()) for v in sent.values())
    undo = call("POST", f"/api/undo/{sent['cancel me']['receipt']}")
    print(f"2. A person cancels the first one: {undo}")

    pid = int(pidfile.read_text().strip())
    os.kill(pid, signal.SIGKILL)
    print(f"3. KAVACH killed (kill -9 {pid}) with '{sent['let me go']['subject']}' still waiting")
    while True:
        try:
            call("GET", "/healthz")
            time.sleep(0.3)
        except Exception:
            break
    log = open(ROOT / ".kavach" / "recovery.log", "w")
    subprocess.Popen([str(ROOT / "scripts" / "demo_up.sh")], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                     start_new_session=True)
    r = ready()
    print(f"   Started again: restored {r['store']['restored']['receipts']} receipts, "
          f"{r['store']['restored']['holds_waiting']} email(s) still waiting, chain valid: {r['chain_valid']}")
    wait = max(0.0, due - time.time()) + 6
    print(f"4. Waiting {wait:.0f} s, past both emails' windows...")
    time.sleep(wait)
    c, g = inbox(sent["cancel me"]["subject"]), inbox(sent["let me go"]["subject"])
    tc, tg = (call("GET", f"/api/trace/{sent[n]['corr']}") for n in ("cancel me", "let me go"))
    v = call("GET", "/api/receipts/verify")
    print("Result (read from Mailpit and from KAVACH's receipts):")
    ok = all([check(c == 0, f"the cancelled email is not in the inbox (found {c})"),
              check(g == 1, f"the other one arrived exactly once (found {g})"),
              check(tc["connector"]["outcome"] == "cancelled before it went out",
                    f"trace {sent['cancel me']['corr']}: {tc['connector']['outcome']}"),
              check(tg["connector"]["outcome"] == "sent", f"trace {sent['let me go']['corr']}: {tg['connector']['outcome']}"),
              check(bool(v["valid"]), f"receipt chain verifies across the crash ({v.get('count')} receipts)")])
    print("RECOVERY OK" if ok else "RECOVERY FAILED")
    return 0 if ok else 1


def restart(pidfile: Path) -> dict:
    pid = int(pidfile.read_text().strip())
    os.kill(pid, signal.SIGKILL)
    while True:
        try:
            call("GET", "/healthz")
            time.sleep(0.3)
        except Exception:
            break
    log = open(ROOT / ".kavach" / "recovery.log", "w")
    subprocess.Popen([str(ROOT / "scripts" / "demo_up.sh")], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                     start_new_session=True)
    return ready()


def kill_switch() -> int:
    """The pause stops what is already waiting, also after a crash: queue an email, kill -9 KAVACH and start it
    again (the tasks in memory are gone), pause every agent, and check the email never arrives."""
    pidfile = ROOT / ".kavach" / "kavach.pid"
    ready(3)
    run = time.strftime("%H%M%S")
    session, subject = f"pause-{run}", f"Pause test {run}: must never arrive"
    rpc(session, "initialize", {"_meta": {"kavach/userRequest": f"Send a pause-test email to {TO}.",
                                          "kavach/user": "scripted-agent", "kavach/role": "analyst"}})
    out = rpc(session, "tools/call", {"name": "mail.send", "arguments": {"to": TO, "subject": subject,
                                                                        "body": "Synthetic test email."}})
    q = json.loads(out["result"]["content"][0]["text"])
    corr = out["result"]["_meta"]["kavach/correlation"]
    print(f"1. Queued '{subject}': hold {q['queued']}, trace {corr}")
    r = restart(pidfile)
    print(f"2. KAVACH killed (kill -9) and started again: {r['store']['restored']['holds_waiting']} email(s) waiting")
    k = call("POST", "/api/kill", {"scope": "global", "reason": "demo: pause after a crash"})
    print(f"3. Kill switch pressed: {k['id']}, cancelled {k['cancelled']}")
    time.sleep(max(0.0, q["recall_until"] - time.time()) + 6)
    n = inbox(subject)
    t = call("GET", f"/api/trace/{corr}")
    call("DELETE", f"/api/kill/{k['id']}")
    print(f"4. Past its window; agents resumed ({k['id']} lifted)")
    ok = all([check(q["queued"] in k["cancelled"], "the pause cancelled the email left waiting from before the crash"),
              check(n == 0, f"it is not in the inbox (found {n})"),
              check(t["connector"]["outcome"] == "cancelled before it went out", f"trace {corr}: {t['connector']['outcome']}")])
    print("PAUSE OK" if ok else "PAUSE FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(kill_switch() if sys.argv[1:] == ["kill-switch"] else main())
