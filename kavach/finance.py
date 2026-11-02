"""Finance checks on facts, not text (F7): IBAN and IFSC validity, sanctions screening, Confirmation of Payee.

* IBAN: ISO 13616 country length and the ISO 7064 mod-97 check digits. A typo or an invented account fails (R30).
* IFSC: the 11-character Indian branch code format (4 letters, 0, 6 alphanumerics).
* Sanctions: vendor names fuzzy-matched (normalised, legal suffixes dropped) against a list in OpenSanctions'
  `targets.simple.csv` format (columns id, schema, name, aliases, ...; download from opensanctions.org: free for
  non-commercial use, commercial use needs their licence). Without a file, a small built-in demo list is used.
  A hit blocks payment (R21).
* Confirmation of Payee: when a lookup of the account holder's name is available (a bank's CoP / penny-drop /
  beneficiary-name API), a name that doesn't match the vendor needs approval (R31). The environment's
  `iban_holders` stands in for that API here.
"""
from __future__ import annotations

import csv
import difflib
import re
from pathlib import Path

IBAN_LENGTHS = {"AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16, "BG": 22, "BH": 22, "BR": 29,
                "CH": 21, "CR": 22, "CY": 28, "CZ": 24, "DE": 22, "DK": 18, "DO": 28, "EE": 20, "EG": 29, "ES": 24,
                "FI": 18, "FO": 18, "FR": 27, "GB": 22, "GE": 22, "GI": 23, "GL": 18, "GR": 27, "GT": 28, "HR": 21,
                "HU": 28, "IE": 22, "IL": 23, "IQ": 23, "IS": 26, "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28,
                "LI": 21, "LT": 20, "LU": 20, "LV": 21, "MC": 27, "MD": 24, "ME": 22, "MK": 19, "MR": 27, "MT": 31,
                "MU": 30, "NL": 18, "NO": 15, "PK": 24, "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22,
                "SA": 24, "SE": 24, "SI": 19, "SK": 24, "SM": 27, "TN": 24, "TR": 26, "UA": 29, "VG": 24, "XK": 20}
IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
LEGAL = re.compile(r"\b(gmbh|ltd|limited|llc|inc|corp|corporation|co|company|plc|bv|nv|sa|ag|pvt|private|llp|"
                   r"fze|fzco|trading|the)\b\.?")
DEMO_SANCTIONS = [  # stand-ins: the repository's synthetic sanctioned vendor and two fictional entities
    {"id": "demo-1", "name": "Fabrikam Trading LLC", "aliases": "Fabrikam Trading;Fabrikam FZE"},
    {"id": "demo-2", "name": "Northwind Shadow Holdings", "aliases": ""},
    {"id": "demo-3", "name": "Contoso Black Sea Shipping", "aliases": "Contoso BSS"},
]


def looks_like_iban(account: str) -> bool:
    """IBAN-shaped (two letters, two digits, then letters/digits). Other formats, e.g. an Indian account number with
    its IFSC or a sandbox TEST-ACCT-001, aren't IBANs and aren't judged as one."""
    return bool(re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{8,30}", re.sub(r"\s", "", str(account or "")).upper()))


def same_account(given, on_record) -> bool:
    """R41: the account the agent named is the one on record (spaces and case ignored); naming none is fine."""
    norm = lambda a: re.sub(r"\s", "", str(a or "")).upper()
    return given is None or (bool(norm(on_record)) and norm(given) == norm(on_record))


def same_amount(given, on_record) -> bool:
    """R41: the amount the agent named is the invoice's (to the paisa / cent); naming none is fine."""
    if given is None:
        return True
    try:
        return abs(float(given) - float(on_record)) < 0.005
    except (TypeError, ValueError):
        return False


def iban_check(iban: str) -> tuple[bool, str]:
    """(valid, why). Spaces and case are ignored; country length and mod-97 must both hold."""
    s = re.sub(r"\s", "", str(iban or "")).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{8,30}", s):
        return False, "not an IBAN"
    country = s[:2]
    if country in IBAN_LENGTHS and len(s) != IBAN_LENGTHS[country]:
        return False, f"{country} IBANs have {IBAN_LENGTHS[country]} characters, this has {len(s)}"
    digits = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    if int(digits) % 97 != 1:
        return False, "check digits don't match (a typo, or a made-up account)"
    return True, "valid"


def ifsc_valid(code: str) -> bool:
    return bool(IFSC.match(str(code or "").upper()))


def normalise_name(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]", " ", str(name or "").lower().replace(".", ""))   # L.L.C. -> llc
    return " ".join(LEGAL.sub(" ", n).split())


def name_similarity(a: str, b: str) -> float:
    x, y = normalise_name(a), normalise_name(b)
    if not x or not y:
        return 0.0
    tokens = difflib.SequenceMatcher(None, " ".join(sorted(x.split())), " ".join(sorted(y.split()))).ratio()
    return max(difflib.SequenceMatcher(None, x, y).ratio(), tokens)


class SanctionsList:
    def __init__(self, entries: list[dict]):
        self.names: list[tuple[str, str, str]] = []          # (normalised name, original, id)
        for e in entries:
            for n in [e.get("name", "")] + [a for a in str(e.get("aliases") or "").split(";") if a.strip()]:
                if normalise_name(n):
                    self.names.append((normalise_name(n), n.strip(), e.get("id", "")))

    @classmethod
    def load(cls, path: str | None = None) -> "SanctionsList":
        """OpenSanctions targets.simple.csv (or any CSV with id,name,aliases); the demo list without a path."""
        if not path:
            return cls(DEMO_SANCTIONS)
        with Path(path).open(newline="", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r.get("schema", "Organization") in ("Organization", "Company",
                                                                                        "LegalEntity", "Person", "")]
        return cls(rows)

    def screen(self, name: str, threshold: float = 0.9) -> dict | None:
        """The best match at or above the threshold: {'match', 'id', 'score'}, or None."""
        target = normalise_name(name)
        if not target:
            return None
        best = max(((name_similarity(target, n), orig, i) for n, orig, i in self.names), default=(0.0, "", ""))
        return {"match": best[1], "id": best[2], "score": round(best[0], 3)} if best[0] >= threshold else None
