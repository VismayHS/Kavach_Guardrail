"""Approval cards in Slack and Microsoft Teams (F8). When a call escalates, the people who can approve it see what it
would do, where each argument came from, which rule asked for them and how many approvers it needs, with a link to
the approval in the KAVACH console. Approving happens in KAVACH (where identity and quorum are checked), never by
clicking in chat.

    KAVACH_SLACK_WEBHOOK=https://hooks.slack.com/services/...      (Slack incoming webhook, Block Kit)
    KAVACH_TEAMS_WEBHOOK=https://...                                (Teams Workflows / incoming webhook, Adaptive Card)
    KAVACH_CONSOLE_URL=https://kavach.example.com                   (links in the cards)
"""
from __future__ import annotations

import queue
import threading


def card_facts(item: dict) -> dict:
    d = item["decision"]
    e = d.get("effect") or {}
    prov = [f"{k}: {v['trust']} (from {', '.join(v['sources'])})" for k, v in (d.get("labels") or {}).items()]
    need = " + ".join(f"{n}x {r.replace('_', ' ')}" for r, n in (item.get("quorum") or {}).items())
    return {"tool": d["call"]["tool"], "reason": d.get("reason", ""), "impact": e.get("summary", ""),
            "reversibility": e.get("reversibility", ""), "provenance": prov[:6], "needs": need or "1 approver",
            "requester": item.get("requester", ""), "hitl": item["id"], "four_eyes": item.get("four_eyes", False)}


def slack_blocks(item: dict, console_url: str = "") -> dict:
    f = card_facts(item)
    prov = "\n".join(f"• {p}" for p in f["provenance"]) or "-"
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Approval needed: {f['tool']}"[:150]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Why:* {f['reason']}\n*Impact:* {f['impact']}\n"
                                                                   f"*Reversible:* {f['reversibility'] or 'unknown'}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Where the arguments came from:*\n{prov}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Needs {f['needs']} · requested by "
                                          f"{f['requester']}{' · four-eyes' if f['four_eyes'] else ''} · {f['hitl']}"}]}]
    if console_url:
        blocks.append({"type": "actions", "elements": [{"type": "button", "style": "primary",
                                                        "text": {"type": "plain_text", "text": "Review in KAVACH"},
                                                        "url": f"{console_url.rstrip('/')}/?hitl={f['hitl']}"}]})
    return {"text": f"KAVACH needs approval: {f['tool']} ({f['needs']})", "blocks": blocks}


def teams_card(item: dict, console_url: str = "") -> dict:
    f = card_facts(item)
    body = [{"type": "TextBlock", "size": "Large", "weight": "Bolder", "text": f"Approval needed: {f['tool']}"},
            {"type": "FactSet", "facts": [{"title": "Why", "value": f["reason"]}, {"title": "Impact", "value": f["impact"]},
                                          {"title": "Reversible", "value": f["reversibility"] or "unknown"},
                                          {"title": "Needs", "value": f["needs"]},
                                          {"title": "Requested by", "value": f["requester"]}]},
            {"type": "TextBlock", "wrap": True, "text": "Where the arguments came from: " + "; ".join(f["provenance"])}]
    actions = ([{"type": "Action.OpenUrl", "title": "Review in KAVACH", "url": f"{console_url.rstrip('/')}/?hitl={f['hitl']}"}]
               if console_url else [])
    return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.4",
        "body": body, "actions": actions}}]}


class ApprovalNotifier:
    """Receipt listener: posts a card for every escalated decision, from a background thread."""

    def __init__(self, gw, slack_url: str | None = None, teams_url: str | None = None, console_url: str = "",
                 transport=None):
        import httpx
        self.gw, self.slack, self.teams, self.console = gw, slack_url, teams_url, console_url
        self.client = httpx.Client(transport=transport, timeout=10)
        self.q: queue.Queue = queue.Queue()
        self.sent, self.failed = 0, 0
        threading.Thread(target=self._run, daemon=True, name="kavach-notify").start()

    def __call__(self, rec: dict) -> None:
        d = (rec["body"].get("decision") or {}) if rec["body"].get("type") == "decision" else {}
        if d.get("verdict") == "ESCALATE" and d.get("hitl_id"):
            self.q.put(d["hitl_id"])

    def _run(self) -> None:
        while True:
            hid = self.q.get()
            item = self.gw.hitl.items.get(hid)
            if item is None:
                continue
            for url, payload in ((self.slack, slack_blocks), (self.teams, teams_card)):
                if not url:
                    continue
                try:
                    self.client.post(url, json=payload(item, self.console)).raise_for_status()
                    self.sent += 1
                except Exception:
                    self.failed += 1

    def flush(self, timeout: float = 5.0) -> None:
        import time
        end = time.time() + timeout
        while not self.q.empty() and time.time() < end:
            time.sleep(0.02)
        time.sleep(0.1)
