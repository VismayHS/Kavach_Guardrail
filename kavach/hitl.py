"""Human-in-the-loop approval queue.

Only escalated actions reach a human, and the human sees a consequence card (what
will change, where each argument came from, reversibility, rule, confidence), not
raw JSON. Safety properties:
  * default-deny on timeout (an unattended queue never turns into an allow)
  * four-eyes: for irreversible, high-harm actions the approver must differ from the requester
  * every human decision is written to the receipt chain and kept as a training label
"""
from __future__ import annotations

import threading
import time
import uuid


class ApprovalQueue:
    def __init__(self, timeout_s: float = 300.0):
        self.timeout_s = timeout_s
        self.items: dict[str, dict] = {}
        self.labels: list[dict] = []          # human feedback -> recalibration data
        self.lock = threading.Lock()

    def submit(self, task_id: str, requester: str, decision: dict, four_eyes: bool) -> str:
        hid = "hitl-" + uuid.uuid4().hex[:6]
        with self.lock:
            self.items[hid] = {"id": hid, "task_id": task_id, "requester": requester, "decision": decision,
                               "four_eyes": four_eyes, "status": "pending", "created": time.time(),
                               "expires": time.time() + self.timeout_s}
        return hid

    def pending(self) -> list[dict]:
        self.expire()
        return [i for i in self.items.values() if i["status"] == "pending"]

    def expire(self) -> None:
        now = time.time()
        with self.lock:
            for i in self.items.values():
                if i["status"] == "pending" and now > i["expires"]:
                    i["status"] = "expired-denied"

    def resolve(self, hid: str, approver: str, approve: bool, mode: str = "execute", note: str = "") -> dict:
        self.expire()
        with self.lock:
            item = self.items.get(hid)
            if item is None or item["status"] != "pending":
                raise ValueError("not pending")
            if approve and item["four_eyes"] and approver == item["requester"]:
                raise PermissionError("four-eyes rule: requester cannot approve their own irreversible action")
            item.update(status=("approved" if approve else "denied"), approver=approver, mode=mode,
                        note=note, resolved=time.time(),
                        wait_s=round(time.time() - item["created"], 1))
            self.labels.append({"features": item["decision"].get("risk", {}) and item["decision"]["risk"]["features"],
                                "label_unsafe": 0 if approve else 1, "tool": item["decision"]["call"]["tool"]})
            return item
