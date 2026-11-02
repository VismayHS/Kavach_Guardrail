"""Demo 1 against a real inbox: with Mailpit running (scripts/demo_up.sh starts one), a cancelled email never
arrives, and one left alone arrives once, carrying its hold id. Skipped when no Mailpit is listening."""
import json
import os
import tempfile
import time
import urllib.parse
import urllib.request
import uuid

import pytest

from kavach.connectors import SmtpMailer
from kavach.environment import MAIL_RECALL_S, Environment
from kavach.gateway import GatewayConfig, Kavach
from kavach.models import ToolCall

MAILPIT = os.environ.get("KAVACH_TEST_MAILPIT", "http://127.0.0.1:8025")


def get(path: str):
    return json.load(urllib.request.urlopen(MAILPIT + path, timeout=3))


def mailpit_up() -> bool:
    try:
        get("/api/v1/info")
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not mailpit_up(), reason=f"no Mailpit at {MAILPIT} (scripts/demo_up.sh starts one)")


def inbox(subject: str) -> list[dict]:
    return get("/api/v1/search?query=" + urllib.parse.quote(f'subject:"{subject}"'))["messages"]


def test_the_inbox_shows_what_the_receipts_say():
    gw = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    gw.env.mailer = SmtpMailer("127.0.0.1", 1025)
    run = uuid.uuid4().hex[:8]
    tid, _ = gw.start_task("ravi", "analyst", "Send this test summary to demo-recipient@example.test.")
    send = lambda subject: gw.run(tid, ToolCall("mail.send", {"to": "demo-recipient@example.test",
                                                               "subject": f"{subject} {run}", "body": "All good."}))
    stop, keep = send("Stop me"), send("Let me go")
    assert gw.undo_action(stop.receipt_id)["undone"]
    gw.settle(time.time() + MAIL_RECALL_S + 1)
    time.sleep(0.5)                                                          # Mailpit stores it asynchronously
    assert inbox(f"Stop me {run}") == []                                      # cancelled: never reached the server
    (m,) = inbox(f"Let me go {run}")                                          # left alone: arrived, once
    assert [t["Address"] for t in m["To"]] == ["demo-recipient@example.test"]
    assert get(f"/api/v1/message/{m['ID']}/headers")["X-Kavach-Outbox"] == [keep.result["queued"]]
    closed = [r["body"] for r in gw.receipts.items if r["body"]["type"] == "window-closed"]
    assert [(c["hold"], c["outcome"]) for c in closed] == [(keep.result["queued"], "sent")]
    urllib.request.urlopen(urllib.request.Request(                          # leave a demo inbox as it was
        MAILPIT + "/api/v1/messages", data=json.dumps({"IDs": [m["ID"]]}).encode(), method="DELETE",
        headers={"Content-Type": "application/json"}), timeout=3)
