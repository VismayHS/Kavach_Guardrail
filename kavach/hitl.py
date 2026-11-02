"""Human-in-the-loop approval queue.

Only escalated actions reach a human, and the human sees a consequence card (what
will change, where each argument came from, reversibility, rule, confidence), not
raw JSON. Safety properties:
  * default-deny on timeout (an unattended queue never turns into an allow)
  * four-eyes: for irreversible, high-harm actions the approver must differ from the requester
  * quorum (N4): a tiered release names the verified roles that must approve ({cfo: 1, finance_director: 1});
    each seat needs a different person, none of them the requester, and the action runs only when all are filled
  * any single reviewer can deny (stopping is always allowed)
  * every human decision is written to the receipt chain and kept as a training label

Scope: this queue decides only when KAVACH is the gateway (API, MCP, proxy). Inside Topaz AgentOS approvals happen
in AgentOS's own queue; KAVACH's escalation message names the approvers the tier needs.
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

    def submit(self, task_id: str, requester: str, decision: dict, four_eyes: bool,
               quorum: dict[str, int] | None = None) -> str:
        hid = "hitl-" + uuid.uuid4().hex[:6]
        with self.lock:
            self.items[hid] = {"id": hid, "task_id": task_id, "requester": requester, "decision": decision,
                               "four_eyes": four_eyes, "status": "pending", "created": time.time(),
                               "expires": time.time() + self.timeout_s,
                               "quorum": dict(quorum or {}), "remaining": dict(quorum or {}), "approvals": []}
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

    def resolve(self, hid: str, approver: str, approve: bool, mode: str = "execute", note: str = "",
                approver_role: str | None = None) -> dict:
        self.expire()
        with self.lock:
            item = self.items.get(hid)
            if item is None or item["status"] != "pending":
                raise ValueError("not pending")
            needs = dict(item.get("remaining") or {})    # never mutate a dict a receipt may already hold
            if approve and (item["four_eyes"] or item.get("quorum")) and approver == item["requester"]:
                raise PermissionError("four-eyes rule: requester cannot approve their own irreversible action")
            if approve and item.get("quorum"):
                seats = ", ".join(f"{n} x {r}" for r, n in needs.items())
                if not approver_role:
                    raise PermissionError(f"this action needs approval from {seats}; the approver's role is required")
                if needs.get(approver_role, 0) < 1:
                    raise PermissionError(f"role '{approver_role}' is not one of the approvers still needed ({seats})")
                if any(a["approver"] == approver for a in item["approvals"]):
                    raise PermissionError("each approval must come from a different person")
                item["approvals"].append({"approver": approver, "role": approver_role, "at": time.time()})
                needs[approver_role] -= 1
                item["remaining"] = {r: n for r, n in needs.items() if n > 0}
                if item["remaining"]:
                    return item                          # still pending: more seats to fill
            item.update(status=("approved" if approve else "denied"), approver=approver, mode=mode,
                        note=note, resolved=time.time(),
                        wait_s=round(time.time() - item["created"], 1))
            self.labels.append({"features": item["decision"].get("risk", {}) and item["decision"]["risk"]["features"],
                                "label_unsafe": 0 if approve else 1, "tool": item["decision"]["call"]["tool"]})
            return item
