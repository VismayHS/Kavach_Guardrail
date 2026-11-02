"""Email recipients, parsed the way mail clients write them (N1).

Agents copy recipient lists from Outlook (`a@x.com; b@y.com`), from headers (`"Ops" <ops@x.com>`), or join
them with commas. Splitting on commas alone read `audit@big4-review.co; ops@infycorp.com` as one address
ending in the internal domain. Every component that looks at recipients uses this one function.
"""
from __future__ import annotations

import re
from email.utils import getaddresses

_ADDR = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")


def parse_recipients(*fields) -> list[str]:
    """Lower-cased addresses from any number of to/cc/bcc strings (or lists of them), in order, without repeats.
    Text that isn't an address (a bare display name) is kept as-is so it still counts as a recipient."""
    raw: list[str] = []
    for f in fields:
        if not f:
            continue
        raw.extend(f if isinstance(f, (list, tuple)) else [str(f)])
    out: list[str] = []
    for chunk in raw:
        for _, addr in getaddresses([chunk.replace(";", ",")]):
            a = addr.strip().strip("'\"").lower()
            if a and a not in out:
                out.append(a)
    return out


def domain_of(addr: str) -> str:
    return addr.rsplit("@", 1)[-1].lower() if "@" in addr else ""


def is_address(addr: str) -> bool:
    return bool(_ADDR.match(addr))
