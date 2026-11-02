"""Signed caller identity (HS256 JWT): the user and role come from the token, never from the request body.

    export KAVACH_AUTH_SECRET=...                      # turns auth on for the API
    python -m kavach.auth mint ravi analyst [hours] [kind]   # prints a token for that user and role

A token's kind says who holds it. The orchestrator (the harness that talks to the user and runs the tools) may state
the user's request and hand over tool outputs. An agent token may only check its own calls inside a session the
orchestrator opened: otherwise a hijacked agent could describe the task, and its own history, however it liked.
Tokens without a kind are orchestrator tokens.

Without KAVACH_AUTH_SECRET the server runs in dev mode: the role is taken from the request,
and every receipt records `authenticated: false`.
"""
from __future__ import annotations

import os
import sys
import time

import jwt

SECRET_ENV = "KAVACH_AUTH_SECRET"


KINDS = ("orchestrator", "agent")


def mint(user: str, role: str, hours: float = 8, secret: str | None = None, kind: str = "orchestrator") -> str:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    secret = secret or os.environ[SECRET_ENV]
    return jwt.encode({"sub": user, "role": role, "kind": kind, "exp": int(time.time() + hours * 3600)}, secret,
                      algorithm="HS256")


def kind_of(claims: dict | None) -> str:
    """Dev mode (no claims) and tokens minted before kinds existed count as the orchestrator."""
    return (claims or {}).get("kind", "orchestrator")


def verify(token: str, secret: str) -> dict:
    """Return the token's claims; raises jwt.PyJWTError if it is forged, expired or incomplete."""
    return jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["sub", "role", "exp"]})


if __name__ == "__main__":
    if len(sys.argv) < 4 or sys.argv[1] != "mint":
        sys.exit("usage: python -m kavach.auth mint <user> <role> [hours] [orchestrator|agent]")
    print(mint(sys.argv[2], sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 else 8,
               kind=sys.argv[5] if len(sys.argv) > 5 else "orchestrator"))
