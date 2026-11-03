"""Agent identity (F1): short-lived, task-scoped tokens by OAuth 2.0 Token Exchange (RFC 8693).

An agent should never carry the user's own long-lived credentials. KAVACH acts as the security token service:

    POST /oauth/token
      grant_type=urn:ietf:params:oauth:grant-type:token-exchange
      subject_token=<the user's KAVACH token>      subject_token_type=urn:ietf:params:oauth:token-type:jwt
      scope="mail.send crm.query"  audience=<the tool / connector>  resource=<task id>  actor=<agent id>

and returns a delegated token (EdDSA-signed with KAVACH's Ed25519 key, 5 minutes by default) whose claims say who it
is for (sub), who acts (act.sub = the agent), which tools it may call (scope: never more than the user's role
allows), for which tool or connector (aud) and which task (task). Tools verify it against GET /.well-known/jwks.json.
"""
from __future__ import annotations

import base64
import time
import uuid

import jwt

TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
JWT_TYPE = "urn:ietf:params:oauth:token-type:jwt"
ISSUER = "kavach"


def jwks(signer) -> dict:
    """The public key as a JSON Web Key Set (OKP / Ed25519), for tools that verify delegated tokens."""
    from cryptography.hazmat.primitives import serialization
    raw = signer._key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    x = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return {"keys": [{"kty": "OKP", "crv": "Ed25519", "x": x, "kid": signer.key_id, "alg": "EdDSA", "use": "sig"}]}


def exchange(subject_claims: dict, allowed_tools: list[str], scope: str = "", audience: str = "", task: str = "",
             actor: str = "agent", ttl_s: int = 300, signer=None) -> dict:
    """Issue a delegated token. Scope is the requested tools intersected with what the user's role may use; asking
    for nothing gets nothing (no implicit 'all')."""
    wanted = [t for t in scope.split() if t]
    granted = [t for t in wanted if "*" in allowed_tools or t in allowed_tools]
    if not granted:
        raise PermissionError("none of the requested tools are allowed for this user's role")
    now = int(time.time())
    claims = {"iss": ISSUER, "sub": subject_claims["sub"], "role": subject_claims.get("role"),
              "tenant": subject_claims.get("tenant", "default"), "act": {"sub": actor}, "scope": " ".join(granted),
              "aud": audience or "kavach-tools", "task": task, "iat": now, "nbf": now, "exp": now + int(ttl_s),
              "jti": uuid.uuid4().hex}
    token = jwt.encode(claims, signer._key, algorithm="EdDSA", headers={"kid": signer.key_id})
    return {"access_token": token, "issued_token_type": JWT_TYPE, "token_type": "Bearer", "expires_in": int(ttl_s),
            "scope": claims["scope"]}


def verify_delegated(token: str, tool: str, audience: str, public_key) -> dict:
    """What a tool or connector checks before acting: signature, issuer, audience, expiry, and that this tool is in
    scope. Returns the claims; raises jwt.PyJWTError or PermissionError otherwise."""
    claims = jwt.decode(token, public_key, algorithms=["EdDSA"], audience=audience, issuer=ISSUER,
                        options={"require": ["exp", "sub", "scope", "aud", "act"]})
    if tool not in claims["scope"].split():
        raise PermissionError(f"token does not grant {tool}")
    return claims
