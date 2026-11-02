"""Deployment profile (A9). `KAVACH_PROFILE=prod` fails closed instead of quietly running in demo mode.

prod requires:
  * KAVACH_AUTH_SECRET (32+ characters): user and role always come from a signed token;
  * KAVACH_RECEIPT_KEY (32+ characters, not the demo key): receipts are signed with a real key;
and turns on pinned tool definitions, and turns off the demo endpoints and the clock fast-forward.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

DEMO_KEYS = {"", "demo-receipt-key"}


class ProfileError(RuntimeError):
    pass


@dataclass(frozen=True)
class Profile:
    name: str
    prod: bool
    require_tool_hash: bool
    demo_endpoints: bool
    fast_forward: bool


def check_profile(environ=None) -> Profile:
    env = os.environ if environ is None else environ
    name = (env.get("KAVACH_PROFILE") or "dev").lower()
    if name != "prod":
        return Profile(name, False, False, True, True)
    problems = []
    if len(env.get("KAVACH_AUTH_SECRET") or "") < 32:
        problems.append("KAVACH_AUTH_SECRET must be set (32+ characters)")
    key = env.get("KAVACH_RECEIPT_KEY") or ""
    if key in DEMO_KEYS or len(key) < 32:
        problems.append("KAVACH_RECEIPT_KEY must be a real key (32+ characters, not the demo key)")
    if problems:
        raise ProfileError("KAVACH_PROFILE=prod refuses to start: " + "; ".join(problems))
    return Profile("prod", True, True, False, False)
