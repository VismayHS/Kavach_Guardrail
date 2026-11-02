"""Signed caller identity (HS256 JWT): the user and role come from the token, never from the request body.

    export KAVACH_AUTH_SECRET=...                      # turns auth on for the API
    python -m kavach.auth mint ravi analyst [hours]    # prints a token for that user and role

Without KAVACH_AUTH_SECRET the server runs in dev mode: the role is taken from the request,
and every receipt records `authenticated: false`.
"""
from __future__ import annotations

import os
import sys
import time

import jwt

SECRET_ENV = "KAVACH_AUTH_SECRET"


def mint(user: str, role: str, hours: float = 8, secret: str | None = None, tenant: str = "default") -> str:
    secret = secret or os.environ[SECRET_ENV]
    return jwt.encode({"sub": user, "role": role, "tenant": tenant, "exp": int(time.time() + hours * 3600)}, secret,
                      algorithm="HS256")


def verify(token: str, secret: str) -> dict:
    """Return the token's claims; raises jwt.PyJWTError if it is forged, expired or incomplete."""
    claims = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["sub", "role", "exp"]})
    claims.setdefault("tenant", "default")          # F10: tokens from before tenants belong to the default tenant
    return claims


if __name__ == "__main__":
    if len(sys.argv) < 4 or sys.argv[1] != "mint":
        sys.exit("usage: python -m kavach.auth mint <user> <role> [hours] [tenant]")
    print(mint(sys.argv[2], sys.argv[3], float(sys.argv[4]) if len(sys.argv) > 4 else 8,
               tenant=sys.argv[5] if len(sys.argv) > 5 else "default"))
