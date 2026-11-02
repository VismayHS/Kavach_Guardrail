"""Part 4: a cut-short receipt log is detected (U10)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach.receipts import ReceiptLog  # noqa: E402

KEY = b"state-test-receipt-key-32-bytes-long"


def test_deleting_the_newest_receipt_is_detected_in_memory():
    log = ReceiptLog(KEY)
    for i in range(3):
        log.append({"n": i})
    assert log.verify()["valid"]
    log.items.pop()                                              # cut the log short
    v = log.verify()
    assert not v["valid"] and "anchor" in v["reason"]
