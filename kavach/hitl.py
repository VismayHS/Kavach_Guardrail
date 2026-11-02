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


FAST_S = 3.0          # an approval this quick is a click, not a review
STREAK = 10           # this many approvals in a row without a single denial is a pattern worth a look


class ApprovalQueue:
    def __init__(self, timeout_s: float = 300.0, chain: list[str] | None = None):
        """chain (F8): who an unanswered request goes to next, e.g. ["team_lead", "finance_manager"]. Each SLA
        period without an answer moves it one step up; only after the last step does it expire (denied)."""
        self.timeout_s = timeout_s
        self.chain = list(chain or [])
        self.items: dict[str, dict] = {}
        self.labels: list[dict] = []          # human feedback -> recalibration data
        self.lock = threading.Lock()
        self.on_event: list = []              # callbacks(event dict): the gateway receipts escalations

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

    def expire(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        events = []
        with self.lock:
            for i in self.items.values():
                while i["status"] == "pending" and now > i["expires"]:
                    level = i.get("level", 0)
                    if level < len(self.chain):            # SLA missed: route up the chain, not straight to deny
                        i["level"], i["routed_to"] = level + 1, self.chain[level]
                        i["expires"] += self.timeout_s
                        events.append({"type": "approval-escalated", "hitl": i["id"], "to": i["routed_to"],
                                       "level": i["level"]})
                    else:
                        i["status"] = "expired-denied"
                        events.append({"type": "approval-expired", "hitl": i["id"], "task_id": i["task_id"]})
        for ev in events:
            for cb in self.on_event:
                cb(ev)

    def stats(self) -> dict:
        """Approval fatigue (F8): per approver, how fast and how uniformly they approve."""
        by: dict[str, list[dict]] = {}
        for i in sorted(self.items.values(), key=lambda x: x.get("resolved", 0)):
            if i.get("approver") and i["status"] in ("approved", "denied"):
                by.setdefault(i["approver"], []).append(i)
        out, warnings = {}, []
        for who, items in by.items():
            waits = sorted(i.get("wait_s", 0.0) for i in items)
            approved = [i for i in items if i["status"] == "approved"]
            fast = sum(1 for i in approved if i.get("wait_s", 0.0) < FAST_S)
            streak = best = 0
            for i in items:
                streak = streak + 1 if i["status"] == "approved" else 0
                best = max(best, streak)
            out[who] = {"decisions": len(items), "approved": len(approved), "denied": len(items) - len(approved),
                        "median_wait_s": waits[len(waits) // 2], "fast_approvals": fast, "longest_approve_streak": best}
            if len(items) >= 5 and fast / max(1, len(approved)) > 0.5:
                warnings.append(f"{who}: {fast} of {len(approved)} approvals took under {FAST_S:.0f} s")
            if best >= STREAK:
                warnings.append(f"{who}: {best} approvals in a row without a single denial")
        return {"approvers": out, "warnings": warnings, "pending": sum(i["status"] == "pending" for i in self.items.values())}

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
