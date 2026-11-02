"""A store written before signed checkpoints existed has receipts and no checkpoint file. It used to be reported as
tampered with (CHAIN BROKEN on every older demo database). The store now marks itself the first time it writes a
checkpoint: with that mark, a missing file was removed (still caught: tests/test_checkpoint.py); without it, the store
is older than checkpoints and is adopted, with a receipt saying where checkpoint coverage starts."""
from sqlalchemy import delete

from kavach.store import Store, meta
from tests.test_checkpoint import boot, stored, work


def legacy(tmp_path):
    """What an older KAVACH left: the receipts, no checkpoint file, no mark."""
    url, gw, cp = stored(tmp_path)
    cp.unlink()
    with Store(url).engine.begin() as c:
        c.execute(delete(meta))
    return url, len(gw.receipts.items)


def test_an_older_store_is_adopted_not_reported_broken(tmp_path):
    url, n = legacy(tmp_path)
    gw, restored = boot(url)
    assert restored["chain_valid"] and restored.get("checkpoint_started") and gw.receipts.verify()["valid"]
    started = gw.receipts.items[-1]["body"]
    assert started["type"] == "checkpoint-started" and started["covers_from"] == n + 1
    work(gw)
    gw2, again = boot(url)                                   # from now on it is checkpointed like any store
    assert again["chain_valid"] and not again.get("checkpoint_started")


def test_once_adopted_removing_the_file_is_caught_again(tmp_path):
    url, _ = legacy(tmp_path)
    boot(url)
    (tmp_path / "kavach.db.checkpoint.json").unlink()
    gw, restored = boot(url)
    assert not restored["chain_valid"] and "missing" in gw.receipts.verify()["reason"]


def test_an_edited_older_store_is_still_broken(tmp_path):
    import json

    from sqlalchemy import update

    from kavach.store import receipts
    url, _ = legacy(tmp_path)
    s = Store(url)
    with s.engine.begin() as c:
        row = c.execute(receipts.select().where(receipts.c.seq == 2)).first()
        rec = json.loads(row.data)
        rec["body"]["request"] = "edited"
        c.execute(update(receipts).where(receipts.c.seq == 2).values(data=json.dumps(rec)))
    gw, restored = boot(url)
    assert not restored["chain_valid"] and not restored.get("checkpoint_started")
