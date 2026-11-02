"""Provenance / taint tracking by value lineage.

Every value the agent could later put into a tool argument is registered with a
label when it first enters the task: the user's request (trusted), or a tool
output (labelled by the tool manifest: e.g. inbox and web content is untrusted,
CRM rows are PII). When a tool call arrives, each argument is matched back to the
values it was built from.

This is an approximation of information-flow control (exact IFC needs the agent
to run inside an interpreter, as in CaMeL / FIDES). Value lineage needs no change
to the agent, which is what makes the gateway drop-in. Its known blind spot
(paraphrased or re-encoded values) is covered by fail-safe defaults: a control
argument that matches nothing the user typed is never labelled "trusted".
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import unquote

from .addresses import domain_of, parse_recipients
from .models import Conf, Label, Trust

URL_SEP = re.compile(r"[/_\-+=&?#;:~]")
EMAIL =re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL = re.compile(r"https?://[^\s\"'<>)]+")
ACCOUNT = re.compile(r"\bACC-\d{2}-\d{4}\b")
PHONE = re.compile(r"\+\d{1,3}[- ]?\d{6,12}\b")                                          # +91-9798935572
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?\b")   # spaced or not
DOCID = re.compile(r"\b[A-Z]{1,5}-\d{3,}\b")                                              # INV-3040, PO-3001
UPI = re.compile(r"\b[\w.-]{2,}@[A-Za-z]{2,}\b(?![\w.-]*\.[A-Za-z])")                    # ravi@okhdfcbank
PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")                                               # Indian tax id
AADHAAR = re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b")                                    # Verhoeff-checked
CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")                                            # Luhn-checked
NUMBER = re.compile(r"(?<![\w.-])\d[\d,]*(?:\.\d+)?(?![\w-])")
TARGET_NUM = re.compile(r"(?<![\w.-])\d{2,}(?![\w-])")
SHORT_ID = re.compile(r"\b(?:customer|client|invoice|record|order|ticket|account|vendor|id)\s*[#:=]?\s*(\d)\b", re.I)
REPLY = re.compile(r"\b(reply|respond|write back)\b", re.I)

_VD = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
       [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
       [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
       [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_VP = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
       [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
       [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _aadhaar_ok(d: str) -> bool:
    """Aadhaar numbers start with 2-9 and carry a Verhoeff check digit."""
    c = 0
    for i, ch in enumerate(reversed(d)):
        c = _VD[c][_VP[i % 8][int(ch)]]
    return d[0] not in "01" and c == 0


def _luhn_ok(d: str) -> bool:
    s = 0
    for i, ch in enumerate(reversed(d)):
        n = int(ch) * (2 if i % 2 else 1)
        s += n - 9 if n > 9 else n
    return 13 <= len(d) <= 19 and s % 10 == 0


def is_pii(e: str) -> bool:
    """Entities that identify a person: emails, UPI ids, phones, PAN, Aadhaar, card numbers."""
    return "@" in e or e.startswith(("+", "pan:", "aadhaar:", "card:", "voter:", "passport:"))


def named_targets(text: str) -> set[str]:
    """Record ids a user names: numbers of 2+ digits, document ids like INV-3040 (also as 3040: "invoice 3040"), and
    one-digit ids after a record word ("customer 3", "id = 3"). A bare one digit is usually a count ("the 3 emails")."""
    text = PHONE.sub(" ", IBAN.sub(" ", text))     # an account or phone number's digit groups aren't record ids
    docs = DOCID.findall(text)
    return set(TARGET_NUM.findall(text)) | set(docs) | {d.rsplit("-", 1)[1] for d in docs} | set(SHORT_ID.findall(text))


RECORD_REF = re.compile(r"\b(?:invoice|customer|client|account|vendor|order|ticket|record|id)s?\s*(?:no\.?|number)?"
                        r"\s*[#:=]?\s*([A-Z]{1,5}-\d{3,}|\d+)\b", re.I)


def named_records(text: str) -> set[str]:
    """Ids the user tied to a record ("invoice 1499", "GL account 400100", "customer 3") plus document ids anywhere.
    When there are any, the argument that picks the record must be one: "refund 1500 on invoice 1499" names no
    record 1500, and "refund 2000 on invoice 1042" doesn't allow refund(invoice_id=2000, amount=1042)."""
    text = PHONE.sub(" ", IBAN.sub(" ", text))
    ids = set(RECORD_REF.findall(text)) | set(DOCID.findall(text))
    return ids | {i.rsplit("-", 1)[1] for i in ids if "-" in i}


def arg_targets(args: dict) -> set[str]:
    """Records an action touches: named_targets of its argument values, plus any whole-number value (invoice_id=3)."""
    vals = [str(v) for v in args.values()]
    return named_targets(" ".join(vals)) | {v for v in vals if v.isdigit()}


def _norm_num(s: str) -> str:
    try:
        v = float(s.replace(",", ""))
        return str(int(v)) if v == int(v) else str(v)
    except ValueError:
        return s


GSTIN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")                    # Indian GST registration
IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")                                        # Indian bank branch code
VOTER = re.compile(r"\b[A-Z]{3}\d{7}\b")                                              # EPIC voter id
PASSPORT = re.compile(r"\b[A-PR-WYa-pr-wy][1-9]\d\s?\d{4}[1-9]\b")                   # Indian passport

# ---- normalisation (E8): undo the obfuscation an injection uses to slip a value past exact matching
_ZW = re.compile("[­​-‏⁠-⁤﻿]")
_AT = re.compile(r"\s*[\[\(\{<]\s*at\s*[\]\)\}>]\s*|\s+at\s+(?=[\w-]+\s*[\[\(\{<]?\s*dot\b)", re.I)
_DOT = re.compile(r"\s*[\[\(\{<]\s*dot\s*[\]\)\}>]\s*|(?<=\w)\s+dot\s+(?=\w)", re.I)
_ACC_SPACED = re.compile(r"\bACC[\s_.]+(\d{2})[\s_.]+(\d{4})\b")
_B64 = re.compile(r"(?<![\w+/=])[A-Za-z0-9+/]{16,}={0,2}(?![\w+/=])")
# letters from other scripts that look Latin (a small, high-value subset of Unicode's confusables)
_CONFUSABLE = str.maketrans({"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j",
                             "ѕ": "s", "ԁ": "d", "ɡ": "g", "ⅼ": "l", "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H",
                             "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Χ": "X", "А": "A",
                             "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
                             "Х": "X"})


def normalize(text: str) -> str:
    """Canonical form for matching values: NFKC, no invisible characters, HTML entities decoded, look-alike letters
    folded, '[at]'/'(dot)' spelled out, spaced account ids joined, and base64 tokens that decode to text appended."""
    import base64
    import binascii
    import html
    import unicodedata
    t = unicodedata.normalize("NFKC", text)
    t = _ZW.sub("", t)
    t = html.unescape(t).translate(_CONFUSABLE)
    t = _DOT.sub(".", _AT.sub("@", t))
    t = _ACC_SPACED.sub(r"ACC-\1-\2", t)
    decoded = []
    for m in _B64.finditer(t):
        try:
            raw = base64.b64decode(m.group(0) + "=" * (-len(m.group(0)) % 4), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if raw.isprintable() and sum(c.isalpha() for c in raw) > len(raw) / 2:
            decoded.append(raw)
    return t + ("\n" + "\n".join(decoded) if decoded else "")


def entities(text: str) -> set[str]:
    """Values worth tracing in a text: as written, and after normalisation (obfuscated copies match too)."""
    out = _entities(text)
    n = normalize(text)
    return out | _entities(n) if n != text else out


def _entities(text: str) -> set[str]:
    out: set[str] = set()
    out |= {"gstin:" + m for m in GSTIN.findall(text)}
    out |= {"ifsc:" + m for m in IFSC.findall(text)}
    out |= {"voter:" + m for m in VOTER.findall(text)}
    out |= {"passport:" + re.sub(r"\s", "", m).upper() for m in PASSPORT.findall(text)}
    out |= {e.lower() for e in EMAIL.findall(text)}
    out |= {u.rstrip(".,") for u in URL.findall(text)}
    out |= set(ACCOUNT.findall(text))
    out |= {re.sub(r"\s", "", m).upper() for m in IBAN.findall(text)}
    out |= set(DOCID.findall(text))
    out |= set(PHONE.findall(text))
    out |= {u.lower() for u in UPI.findall(text)}
    out |= {"pan:" + m for m in PAN.findall(text)}
    out |= {"aadhaar:" + d for d in map(_digits, AADHAAR.findall(text)) if _aadhaar_ok(d)}
    out |= {"card:" + d for d in map(_digits, CARD.findall(text)) if _luhn_ok(d)}
    out |= {"#" + _norm_num(n) for n in NUMBER.findall(text) if len(n.replace(",", "")) >= 3}
    return out


def shingles(text: str, k: int = 6) -> set[str]:
    words = re.findall(r"[a-z0-9@._-]+", text.lower())
    return {" ".join(words[i:i + k]) for i in range(max(0, len(words) - k + 1))}


@dataclass
class ProvenanceTracker:
    user_entities: set[str] = field(default_factory=set)
    origins: dict[str, list[Label]] = field(default_factory=dict)
    untrusted_shingles: dict[str, str] = field(default_factory=dict)   # shingle -> source
    pii_values: set[str] = field(default_factory=set)
    user_text: str = ""
    private_seen: bool = False      # the task has read PII / confidential data (lethal-trifecta leg 1)
    untrusted_seen: bool = False    # the task has read untrusted content (lethal-trifecta leg 2)
    senders: dict[str, str] = field(default_factory=dict)          # From: address of a message read -> source
    pii_owner: dict[str, set[str]] = field(default_factory=dict)   # PII value -> the records (people) it belongs to
    n_outputs: int = 0
    lookalike: object | None = None      # kavach.lookalike.Lookalike; a lookalike sender is never "reply to sender"
    hostile: set[str] = field(default_factory=set)                 # sources an injection classifier flagged (C3)

    def register_user(self, text: str) -> None:
        self.user_text += " " + text
        self.user_entities |= entities(text)

    def mask(self, text: str) -> str:
        """Replace PII values that came from private tool outputs with [PII] (for receipts and logs)."""
        def hide(norm):
            return lambda m: "[PII]" if norm(m.group(0)) in self.pii_values else m.group(0)
        for rx, norm in ((EMAIL, str.lower), (UPI, str.lower), (PHONE, str), (PAN, lambda s: "pan:" + s),
                         (AADHAAR, lambda s: "aadhaar:" + _digits(s)), (CARD, lambda s: "card:" + _digits(s))):
            text = rx.sub(hide(norm), text)
        return text

    def register_output(self, tool: str, output, trust: str, conf: Conf, untrusted_fields=(), _rid=None) -> None:
        """Label everything a tool returned. With untrusted_fields, each record is split: those fields (free text
        someone else wrote) are untrusted, the rest keeps `trust` (field-level labels, as in FIDES)."""
        self.private_seen |= conf in (Conf.PII, Conf.CONFIDENTIAL)
        self.untrusted_seen |= trust == "untrusted" or bool(untrusted_fields)
        records = output if isinstance(output, list) else [output]
        if untrusted_fields:
            for rec in records:
                if not isinstance(rec, dict):
                    self.register_output(tool, [rec], "untrusted", conf)
                    continue
                rid = rec.get("id")
                self.register_output(tool, [{k: v for k, v in rec.items() if k not in untrusted_fields}], trust,
                                     conf, _rid=rid)
                self.register_output(tool, [{k: v for k, v in rec.items() if k in untrusted_fields}], "untrusted",
                                     conf, _rid=rid)
            return
        self.n_outputs += 1
        for i, rec in enumerate(records):
            src = f"tool:{tool}"
            rid = _rid if _rid is not None else (rec.get("id") if isinstance(rec, dict) else None)
            if rid is not None:
                src += f"#{rid}"
            record_key = f"{src}@{self.n_outputs}:{i}"      # one person's row: their email, phone... share it
            if tool == "mail.read_inbox" and isinstance(rec, dict) and rec.get("from"):
                for addr in parse_recipients(str(rec["from"])):    # the header, not addresses written in the body
                    self.senders[addr] = src
            text = rec if isinstance(rec, str) else json.dumps(rec, default=str)
            t = Trust(trust) if trust in ("untrusted", "derived", "trusted") else Trust.DERIVED
            lab = Label(t, conf, [src])
            for e in entities(text):
                pii = is_pii(e)
                e_conf = conf if (conf != Conf.PII or pii) else Conf.CONFIDENTIAL
                self.origins.setdefault(e, []).append(Label(t, e_conf, [src]))
                if conf == Conf.PII and pii:
                    self.pii_values.add(e)
                    self.pii_owner.setdefault(e, set()).add(record_key)
            if lab.trust == Trust.UNTRUSTED:
                for sh in shingles(text):
                    self.untrusted_shingles.setdefault(sh, src)

    def third_party_pii(self, recipients: list[str], text: str) -> int:
        """R17: PII values in `text` that belong to someone other than the recipients themselves."""
        rcpt = {r.strip().lower() for r in recipients if r.strip()}
        mine = set().union(*(self.pii_owner.get(r, set()) for r in rcpt))
        return sum(1 for e in entities(text)
                   if e in self.pii_values and e not in rcpt and not (self.pii_owner.get(e, set()) & mine))

    def reply_trusted(self, sender: str) -> bool:
        """'Reply to the sender' trust: not for lookalike domains (R25), nor for a message a classifier flagged."""
        if self.lookalike is not None and self.lookalike.check(domain_of(sender)):
            return False
        return self.senders.get(sender) not in self.hostile

    def given(self, value: str) -> bool:
        """The user typed this value, or asked to reply to the message it came from."""
        return any(s == "user" or s.startswith("sender:") for s in self.label(value, is_control=True).sources)

    def label(self, value, is_control: bool) -> Label:
        text = value if isinstance(value, str) else str(value)
        is_url = text.startswith(("http://", "https://"))
        if is_url:
            text = unquote(text)    # %2B91-9... in a query string is still a phone number
        ents = entities(text) if isinstance(value, str) else {"#" + _norm_num(text)}
        if is_url:                  # /q3/south-12.4/west-9.8: values glued to words by URL separators (N2)
            ents |= {e for e in entities(URL_SEP.sub(" ", text.split("://", 1)[-1])) if e.startswith("#")}
        pii = sum(1 for e in ents if e in self.pii_values)
        conf = Conf.PII if pii else Conf.INTERNAL
        sources: list[str] = []
        trust = Trust.DERIVED

        # 1) verbatim copy of untrusted text (e.g. an injected SQL statement or instruction)
        copied = {self.untrusted_shingles[s] for s in shingles(text) if s in self.untrusted_shingles}
        if copied:
            trust, sources = Trust.UNTRUSTED, sorted(copied)

        # 2) entity lineage: where did each address / account / amount come from?
        for e in ents:
            if e in self.user_entities:
                if trust != Trust.UNTRUSTED or not is_control:
                    sources.append("user")
                continue
            if is_control and e in self.senders and REPLY.search(self.user_text):
                if self.reply_trusted(e):
                    sources.append(f"sender:{self.senders[e]}")   # the user asked to reply to this message's sender
                else:   # the user asked to reply, but the sender is suspect: a human checks it (R25), not a hard block
                    sources.append(f"suspect-sender:{self.senders[e]}")
                continue
            for lab in self.origins.get(e, []):
                sources.extend(lab.sources)
                if lab.trust == Trust.UNTRUSTED:
                    trust = Trust.UNTRUSTED
                if lab.conf.rank > conf.rank:
                    conf = lab.conf

        if is_control and ents and all(e in self.user_entities for e in ents) and not copied:
            trust = Trust.TRUSTED
        if not sources:
            sources = ["agent"]
        return Label(trust, conf, sorted(set(sources)), pii)
