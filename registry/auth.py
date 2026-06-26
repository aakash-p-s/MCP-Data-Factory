"""
backend/registry/auth.py

Gap fix — registry-api previously had ZERO authentication.
This module requires any valid (non-expired, correctly-signed)
Keycloak token on every request. No specific role required — just not anonymous.

PRD reference: Section 5.6 / Section 6.4.1
"""

import os
import httpx
from functools import lru_cache
from fastapi import Request, HTTPException
from jose import jwt, JWTError


JWKS_URL  = os.environ["KEYCLOAK_JWKS_URL"]
AUDIENCE  = os.environ.get("KEYCLOAK_AUDIENCE", "patient-risk-agent")


@lru_cache(maxsize=1)
def _fetch_jwks() -> dict:
    """Fetch Keycloak public keys once and cache them (refreshed on restart)."""
    resp = httpx.get(JWKS_URL, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _matching_key(token: str) -> dict:
    """Return the JWKS key whose kid matches this token's header."""
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")
    for key in _fetch_jwks().get("keys", []):
        if key.get("kid") == kid:
            return key
    raise HTTPException(
        status_code=401,
        detail={"error": {"code": "unauthorized", "reason": "No matching signing key in JWKS"}}
    )


def require_valid_token(request: Request) -> dict:
    """
    FastAPI dependency — use as:  Depends(require_valid_token)

    Accepts any valid, non-expired Keycloak token.
    Does NOT check role — just confirms the token is real and not expired.
    Returns decoded claims dict on success.
    Raises HTTP 401 on missing / expired / invalid token.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error": {
                "code": "unauthorized",
                "reason": "Missing or malformed Authorization header — expected 'Bearer <token>'"
            }}
        )

    token = auth.removeprefix("Bearer ").strip()

    try:
        key = _matching_key(token)
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=AUDIENCE,
            options={"verify_at_hash": False},
        )
        return claims
    except JWTError as exc:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "unauthorized", "reason": str(exc)}}
        ) from exc
