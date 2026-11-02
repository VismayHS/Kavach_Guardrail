"""A receipt chain can't tell it was cut short: deleting the newest receipts leaves a valid chain. A signed
checkpoint (count + head hash), kept apart from the log, catches that, in memory and across a restart (E5 store)."""
import json
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import delete  # noqa: E402

from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.models import ToolCall  # noqa: E402
from kavach.store import Store, attach, receipts  # noqa: E402


def boot(url):
    gw = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    return gw, attach(gw, Store(url))


def work(gw, n=3):
    tid, _ = gw.start_task("asha", "analyst", "Count customers.")
    for _ in range(n):
        gw.run(tid, ToolCall("crm.query", {"sql": "SELECT COUNT(*) FROM customers"}))


def stored(tmp_path):
    url = f"sqlite:///{tmp_path}/kavach.db"
    gw, _ = boot(url)
    work(gw)
    return url, gw, Path(f"{tmp_path}/kavach.db.checkpoint.json")


def test_deleting_the_newest_receipt_is_caught_in_memory():
    gw = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    work(gw)
    assert gw.receipts.verify()["valid"]
    gw.receipts.items.pop()
    v = gw.receipts.verify()
    assert not v["valid"] and v["reason"].startswith("checkpoint")


def test_deleting_the_newest_receipts_from_the_store_is_caught_on_restart(tmp_path):
    url, gw, _ = stored(tmp_path)
    n = len(gw.receipts.items)
    with gw.store.engine.begin() as c:
        c.execute(delete(receipts).where(receipts.c.seq > n - 2))
    _, restored = boot(url)
    assert restored["receipts"] == n - 2 and not restored["chain_valid"]


def test_removing_the_checkpoint_file_is_caught(tmp_path):
    url, _, cp = stored(tmp_path)
    assert cp.exists()
    cp.unlink()
    gw2, restored = boot(url)
    assert not restored["chain_valid"] and "missing" in gw2.receipts.verify()["reason"]


def test_a_forged_checkpoint_is_refused(tmp_path):
    url, _, cp = stored(tmp_path)
    forged = json.loads(cp.read_text())
    forged["count"] -= 1
    cp.write_text(json.dumps(forged))
    _, restored = boot(url)
    assert not restored["chain_valid"]


def test_restarts_and_new_receipts_keep_the_checkpoint_valid(tmp_path):
    url, gw, cp = stored(tmp_path)
    gw2, restored = boot(url)
    assert restored["chain_valid"]
    work(gw2, 2)
    assert json.loads(cp.read_text())["count"] == len(gw2.receipts.items)
    assert boot(url)[1]["chain_valid"]
