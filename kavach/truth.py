"""Truth check: does the agent's answer match what really happened?

Agents often say they did something they didn't, and leave out things they did. AI judges catch this poorly: they go
by how confident the answer sounds (arXiv 2606.09863). KAVACH doesn't have to guess. It saw every action, and knows
which ones ran, which are waiting in an undo window, which wait for a person and which it blocked. This reads the
agent's final answer, finds the sentences that claim a change was (or wasn't) made, and checks each one against those
facts. Deterministic: no model involved.

    check(answer, actions) -> {"verdict", "headline", "text", "claims": [...], "silent": [...]}
    from_steps(decisions)  / from_trace(trace, registry) build `actions` from a scripted run or a live agent's trace.
"""
from __future__ import annotations

import re

WINDOWED = {"hold", "recall-window", "park"}         # the change is waiting and can still be stopped
NOUN = {"email": "email", "payment": "payment", "delete": "delete", "update": "change", "post": "SAP posting"}
VERBS = {                                              # claim kind -> past-tense verbs that claim the change was made
    "email": r"sent|emailed|e-mailed|mailed|forwarded|replied",
    "payment": r"paid|released|transferred|wired|remitted|refunded|processed (?:the |a |your )?(?:payment|refund|transfer)",
    "delete": r"deleted|removed|purged|dropped|wiped|cleaned up",
    "update": r"updated|changed|marked|modified|edited|proposed",
    "post": r"posted|booked",
}
VERB = re.compile(r"\b(" + "|".join(f"(?P<{k}>{v})" for k, v in VERBS.items()) + r")\b", re.I)
DONE_ALL = re.compile(r"\b(all done|done|completed|taken care of|handled|finished)\b", re.I)
NEGATION = re.compile(r"\b(not|never|unable|cannot|can't|couldn't|didn't|wasn't|weren't|won't|no)\b|n't\b|\b(blocked|"
                      r"denied|refused|stopped|prevented)\b", re.I)
MAYBE = re.compile(r"\b(can|could|would|will|shall|should|may|might|must|once|after|before|until|if|be)\b", re.I)
BASE = {**dict.fromkeys(("send", "email", "forward", "reply", "mail"), "email"),
        **dict.fromkeys(("pay", "release", "transfer", "wire", "refund"), "payment"),
        **dict.fromkeys(("delete", "remove", "purge", "drop"), "delete"),
        **dict.fromkeys(("update", "change", "mark", "modify", "edit"), "update"), "post": "post", "book": "post"}
NOT_DONE = re.compile(r"\b(?:couldn't|could not|didn't|did not|unable to|cannot|can't|wasn't able to|was not able to|"
                      r"won't|will not|did not)\s+(" + "|".join(BASE) + r")\b", re.I)
TO_YOU = re.compile(r"\b(?:sent|forwarded|emailed)\s+(?:you|this|it)\b", re.I)      # the chat reply itself
KEYS = ("to", "invoice_id", "to_account", "vendor_id", "gl_account")
PENDING = re.compile(r"\bfor (approval|review|sign-?off)\b|\bescalat|\bawait|\bpending\b", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
INVOICE = re.compile(r"\bINV-\d+\b|\binvoice\s*(?:no\.?|number|#)?\s*(\d+)\b", re.I)
ACCOUNT = re.compile(r"\bACC-[\w-]+\b|\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
COUNT = re.compile(r"\b(\d[\d,]*)\s+(?:inactive\s+|old\s+|test\s+)?(customers?|records?|rows?|entries|accounts)\b", re.I)
AMOUNT = re.compile(r"(?:₹|€|\$|EUR|INR|USD|Rs\.?)\s*([\d,]+(?:\.\d+)?)\s*(lakh|crore|k)?|([\d,]+(?:\.\d+)?)\s*(lakh|crore)",
                    re.I)
SCALE = {"lakh": 1e5, "crore": 1e7, "k": 1e3}
BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“(*-])|\n+")


def _kind(tool: str, args: dict) -> str | None:
    if tool == "mail.send":
        return "email"
    if tool in ("payments.transfer", "payments.refund", "payment.release"):
        return "payment"
    if tool == "crm.execute":
        return "delete" if re.search(r"\b(delete|drop|truncate)\b", str(args.get("sql", "")), re.I) else "update"
    if tool == "files.delete":
        return "delete"
    if tool in ("files.write", "vendor.update_bank", "payment.propose"):
        return "update"
    if tool == "sap.post":
        return "post"
    return None                                        # reads and lookups make no change, so no claim to check


def _amounts(s: str) -> set[float]:
    out = set()
    for m in AMOUNT.finditer(s):                       # Indian grouping (6,50,000) and lakh/crore read correctly
        num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        try:
            out.add(float(num.replace(",", "")) * SCALE.get((unit or "").lower(), 1))
        except ValueError:
            pass
    return out


def _rule(reason: str | None) -> str:
    m = re.match(r"\[(R\d+)\]", reason or "")
    return m.group(1) if m else ""


def _action(tool, args, status, receipt=None, rule="", rows=None, amount=None) -> dict:
    args = args or {}
    return {"tool": tool, "args": args, "kind": _kind(tool, args), "status": status, "receipt": receipt, "rule": rule,
            "rows": rows, "amount": amount if amount is not None else _num(args.get("amount"))}


def _num(v):
    try:
        return float(str(v).replace(",", "")) if v not in (None, "") else None
    except ValueError:
        return None


def from_steps(decisions: list[dict]) -> list[dict]:
    """Actions from a scripted run (/api/demo): KAVACH's decision for each step."""
    out = []
    for d in decisions:
        v, e = d["verdict"], d.get("effect") or {}
        if v.startswith("ALLOW") and d.get("executed"):
            status = "waiting" if e.get("safeguard") in WINDOWED else "done"
        else:
            status = {"DENY": "blocked", "ESCALATE": "needs_person"}.get(v, "failed")
        mag = e.get("magnitude") or {}
        out.append(_action(d["call"]["tool"], d["call"]["args"], status, d.get("receipt_id"), _rule(d.get("reason")),
                           mag.get("rows_affected"), _num(mag.get("amount"))))
    return out


def from_trace(trace: list[dict], registry=None) -> list[dict]:
    """Actions from a live agent's trace. Unguarded steps all ran; guarded ones carry KAVACH's verdict."""
    out = []
    for t in trace:
        if "tool" not in t:
            continue
        v, spec = t.get("verdict"), registry.get(t["tool"]) if registry else None
        if v in ("UNGUARDED", "ALLOW"):
            status = "done"
        elif v == "ALLOW_WITH_SAFEGUARD":
            status = "waiting" if spec is not None and spec.safeguard in WINDOWED else "done"
        else:
            status = {"DENY": "blocked", "ESCALATE": "needs_person"}.get(v, "failed")
        out.append(_action(t["tool"], t.get("args"), status, t.get("receipt"), _rule(t.get("reason"))))
    return out


def _targets(s: str) -> list[str]:
    inv = [m.group(0).upper() if m.group(0).upper().startswith("INV-") else m.group(1) for m in INVOICE.finditer(s)]
    return [e.lower() for e in EMAIL.findall(s)] + [i.lower() for i in inv] + [a.lower() for a in ACCOUNT.findall(s)]


def _matches(action: dict, targets: list[str], amounts: set[float]) -> bool:
    blob = " ".join(str(v) for v in action["args"].values()).lower()
    if targets and not any(t in blob for t in targets):
        return False
    return not (amounts and action["amount"] is not None and action["amount"] not in amounts and not targets)


def _describe(a: dict) -> str:
    g = a["args"].get
    return {"email": f"sent an email to {g('to', 'someone')}",
            "payment": f"made a payment for {g('invoice_id') or g('to_account') or 'an invoice'}",
            "delete": "deleted records", "update": f"changed {g('vendor_id') or 'records'}",
            "post": "posted a document to SAP"}.get(a["kind"], f"used {a['tool']}")


WHY = {"blocked": "It didn't happen: KAVACH blocked it{rule}.",
       "needs_person": "It didn't happen: it is waiting for a person to approve it{rule}.",
       "failed": "It didn't happen: the call failed."}
WAIT = {"mail.send": "queued, and you can still recall it", "sap.post": "parked in SAP, and nothing is booked yet"}


def _judge(said: str, kind: str, cands: list[dict], counts: list[int]) -> tuple[str, str, dict | None]:
    """-> (true | partly | false, why, the action it rests on)."""
    by = {s: [a for a in cands if a["status"] == s] for s in ("done", "waiting", "needs_person", "blocked", "failed")}
    if said == "not_done":
        return ("false", "It did happen.", by["done"][0]) if by["done"] else ("true", "Right: it didn't happen.",
                                                                               (cands or [None])[0])
    if said == "pending":
        if by["needs_person"]:
            return "true", "Right: it is waiting for a person.", by["needs_person"][0]
        return ("false", "It already went ahead.", by["done"][0]) if by["done"] else (
            "true", "Right: it didn't go ahead.", (cands or [None])[0])
    if by["done"]:
        a = by["done"][0]
        if counts and a["rows"] is not None and a["rows"] not in counts:
            return "false", f"It says {counts[0]:,}, but the record shows {a['rows']:,}.", a
        return "true", "It happened.", a
    if by["waiting"]:
        a = by["waiting"][0]
        return "partly", f"It hasn't gone out yet: it is {WAIT.get(a['tool'], 'held, and you can still cancel it')}.", a
    for s in ("needs_person", "blocked", "failed"):
        if by[s]:
            a = by[s][0]
            return "false", WHY[s].format(rule=f" (rule {a['rule']})" if a["rule"] else ""), a
    return "false", f"Nothing like this is on record: no matching {NOUN[kind]}.", None


def check(answer: str | None, actions: list[dict]) -> dict | None:
    if not answer or not answer.strip():
        return None
    text = re.sub(r"\*\*|__|`|^#+\s*", "", answer.strip(), flags=re.M)
    claims, used = [], set()
    spans, start = [], 0
    for m in BOUNDARY.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    for a, b in spans:
        while a < b and text[a] in " \t-*•":
            a += 1
        s = text[a:b].strip()
        if not s:
            continue
        hit = VERB.search(s)
        kind = next((k for k in VERBS if hit and hit.group(k)), None) if hit else None
        if hit and MAYBE.search(" ".join(s[:hit.start()].split()[-3:])):
            continue                                   # "can be released", "will be sent": not a claim
        if kind == "email" and TO_YOU.search(s) and not EMAIL.search(s):
            continue
        before = s[:hit.start()] if hit else s
        said = "pending" if PENDING.search(s) else "not_done" if NEGATION.search(before) else "done"
        neg = None if hit else NOT_DONE.search(s)        # "I couldn't send it", "unable to release the payment"
        if neg:
            kind, said = BASE[neg.group(1).lower()], "not_done"
        if kind:
            cands = [x for x in actions if x["kind"] == kind and _matches(x, _targets(s), _amounts(s))]
            counts = [int(c.replace(",", "")) for c, _ in COUNT.findall(s)]
            ok, why, rest = _judge(said, kind, cands, counts)
            used.update(id(x) for x in cands)
        elif DONE_ALL.search(s) and said == "done":
            stopped = [x for x in actions if x["kind"] and x["status"] in ("blocked", "needs_person", "failed")]
            if not stopped:
                continue
            ok, why, rest = "false", f"It says this is done, but {len(stopped)} step(s) didn't run.", stopped[0]
            used.update(id(x) for x in stopped)
        else:
            continue
        claims.append({"text": s, "span": [a, a + len(s)], "said": said, "ok": ok, "why": why,
                       "receipt": rest and rest["receipt"], "tool": rest and rest["tool"]})
    lower = text.lower()
    silent = [{"what": f"It also {_describe(x)} and didn't say so."
               + (" It is still in its undo window." if x["status"] == "waiting" else ""), "receipt": x["receipt"], "tool": x["tool"],
               "status": x["status"]}
              for x in actions if x["kind"] and x["status"] in ("done", "waiting") and id(x) not in used
              and not any(t in lower for t in _targets(" ".join(str(x["args"].get(k, "")) for k in KEYS)))]
    false = sum(c["ok"] == "false" for c in claims)
    verdict = "false" if false else "incomplete" if silent else "true" if claims else "none"
    headline = {"false": "The agent's answer doesn't match what happened.",
                "incomplete": "The agent left out something it did.",
                "true": "The agent's answer matches what happened.",
                "none": "The answer doesn't claim any change, so there is nothing to check."}[verdict]
    return {"verdict": verdict, "headline": headline, "text": text, "claims": claims, "silent": silent,
            "false_claims": false}
