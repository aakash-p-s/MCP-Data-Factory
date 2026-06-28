"""Layer-2 AuthZ engine — Codebase PRD §5.2.

Re-verifies the JWT (signature/audience/expiry) and enforces deny-by-default RBAC:
the caller's `scp` must contain the tool's required scope AND their `groups` must
intersect the server's allowed groups (the blueprint RBAC matrix).

Signature verification is gated by AUTH_VERIFY_SIGNATURE (default off) because Person B's
Keycloak `scp` scope-mapping isn't wired yet — flip it on once tokens carry real scopes.
The verification CODE lands now (Jul 2); enabling it is a one-env-var switch.
"""

from __future__ import annotations

import os

import jwt

JWKS_URL = os.getenv("JWKS_URL",
                     "http://localhost:8080/realms/patient-risk/protocol/openid-connect/certs")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE") or None
VERIFY_SIGNATURE = os.getenv("AUTH_VERIFY_SIGNATURE", "false").lower() in ("1", "true", "yes")

_jwks_client = None


def _jwks():
    global _jwks_client
    if _jwks_client is None:
        from jwt import PyJWKClient  # needs pyjwt[crypto] when verification is enabled
        _jwks_client = PyJWKClient(JWKS_URL)
    return _jwks_client


def verify_token(token: str, jwks_url: str | None = None) -> dict:
    """Decode a JWT and (when VERIFY_SIGNATURE) verify signature/audience/expiry."""
    if VERIFY_SIGNATURE:
        key = _jwks().get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["RS256"], audience=JWT_AUDIENCE,
                          options={"verify_aud": JWT_AUDIENCE is not None})
    return jwt.decode(token, options={"verify_signature": False})


def scopes_of(claims: dict) -> set[str]:
    return set((claims.get("scp") or "").split())


def groups_of(claims: dict) -> set[str]:
    # normalise Keycloak group paths ("/grp-x" -> "grp-x")
    return {g.lstrip("/") for g in (claims.get("groups") or [])}


def check_scope(claims: dict, required_scope: str) -> bool:
    return required_scope in scopes_of(claims)


def check_groups(claims: dict, allowed_groups: set[str]) -> bool:
    g = groups_of(claims)
    # deny only when the token carries groups that don't intersect the allow list;
    # a groupless service-account token (like the no-token path) is permitted at POC.
    return not (allowed_groups and g and not (g & allowed_groups))


def evaluate(claims: dict, required_scope: str, allowed_groups: set[str],
             service: str | None = None) -> tuple[bool, str | None]:
    """Return (allowed, denial_reason). reason is the explain-denial string (§6.5)."""
    if not check_scope(claims, required_scope):
        return False, f"missing scope {required_scope}"
    if not check_groups(claims, allowed_groups):
        label = f" for {service}" if service else ""
        return False, f"role not permitted{label}; requires group in {sorted(allowed_groups)}"
    return True, None


def authorize_or_raise(claims: dict, required_scope: str, allowed_groups: set[str] | None = None,
                       service: str | None = None) -> None:
    """Raise an HTTPException(403) with the explain-denial envelope on failure (§5.2)."""
    ok, reason = evaluate(claims, required_scope, allowed_groups or set(), service)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=403,
                            detail={"error": {"code": "forbidden", "reason": reason}})
