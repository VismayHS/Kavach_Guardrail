"""Lookalike domains: business email compromise and vendor impersonation (N3, rule R25).

A domain is a lookalike when it is NOT one of the protected domains (the company's own and its known vendors')
but is close enough to one that a person skimming would take it for it. Checks, in the spirit of dnstwist's
permutation families:
  * homoglyphs and digit swaps   infyc0rp.com, lnfycorp.com, rn -> m
  * typos                        infycorpp.com, infcorp.com (Damerau-Levenshtein <= 2 on the name part)
  * same name, another TLD        infycorp.co, northwind-supplies.net
  * the name plus a word          infycorp-finance.co, secure-infycorp.com
Subdomains of a protected domain (docs.infycorp.com) are the protected domain itself, not lookalikes.
"""
from __future__ import annotations

import re

HOMOGLYPHS = str.maketrans({"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "@": "a",
                            "i": "l", "|": "l"})
MULTI = [("rn", "m"), ("vv", "w"), ("cl", "d")]
# second-level suffixes that belong to the TLD (co.uk, com.au, co.in...)
SECOND_LEVEL = {"co", "com", "net", "org", "gov", "ac", "edu"}


def registered(domain: str) -> tuple[str, str]:
    """('infycorp', 'com') for infycorp.com, docs.infycorp.com; ('acme', 'co.uk') for mail.acme.co.uk."""
    parts = [p for p in domain.lower().strip(".").split(".") if p]
    if len(parts) >= 3 and parts[-2] in SECOND_LEVEL and len(parts[-1]) == 2:
        return parts[-3], ".".join(parts[-2:])
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    return (parts[0] if parts else ""), ""


def _skeleton(name: str) -> str:
    s = name.lower()
    for a, b in MULTI:
        s = s.replace(a, b)
    return s.translate(HOMOGLYPHS).replace("-", "").replace("_", "")


def _dl(a: str, b: str) -> int:
    """Damerau-Levenshtein (optimal string alignment) distance."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


class Lookalike:
    def __init__(self, protected: list[str]):
        self.protected = sorted({p.lower().strip(".") for p in protected if p})
        self.names = {registered(p)[0]: p for p in self.protected}

    def is_protected(self, domain: str) -> bool:
        d = domain.lower().strip(".")
        return any(d == p or d.endswith("." + p) for p in self.protected)

    def check(self, domain: str) -> str | None:
        """The protected domain this one imitates, or None."""
        d = (domain or "").lower().strip(".")
        if not d or self.is_protected(d):
            return None
        name, _tld = registered(d)
        sk = _skeleton(name)
        tokens = set(re.split(r"[-_.]", name))
        for pname, pdom in self.names.items():
            if len(pname) < 4:
                continue
            psk = _skeleton(pname)
            if name == pname or sk == psk:                       # other TLD, or homoglyph swap
                return pdom
            if pname in tokens or (len(pname) >= 5 and pname in name):   # brand plus a word
                return pdom
            if len(pname) >= 5 and _dl(sk, psk) <= (1 if len(pname) < 8 else 2):   # typo
                return pdom
        return None
