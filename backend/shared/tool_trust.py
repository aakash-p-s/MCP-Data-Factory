"""Tool-trust / tool-poisoning guard — Person A PRD §5.3.

Two protections, both gated off by default for POC dev (direct :8001-8004 curls must
keep working) and flipped on once Person B's gateway injects the trust header:

  1. Kong-origin check — a production MCP server should only answer requests that arrived
     THROUGH its registered Kong route, not arbitrary direct callers. When
     `TOOL_TRUST_ENFORCE=true`, the request must carry a shared secret header that only
     Kong injects (`X-Kong-Trust: <KONG_TRUST_SECRET>`), or one of Kong's own proxy
     markers (`X-Kong-Request-Id` / `Via`). Default off → all callers allowed (dev).

  2. Tool-poisoning check — the set of tools a server exposes must match the frozen
     blueprint exactly. `assert_registered_tools()` catches a tool injected/renamed at
     runtime (e.g. a poisoned description), turning a silent drift into a startup error.
"""

from __future__ import annotations

import os

ENFORCE = os.getenv("TOOL_TRUST_ENFORCE", "false").lower() in ("1", "true", "yes")
KONG_TRUST_SECRET = os.getenv("KONG_TRUST_SECRET", "")
_KONG_MARKERS = ("x-kong-request-id", "via")


def verify_kong_origin(headers: dict[str, str]) -> tuple[bool, str | None]:
    """Return (trusted, reason). Allows everything unless TOOL_TRUST_ENFORCE is set."""
    if not ENFORCE:
        return True, None
    if KONG_TRUST_SECRET and headers.get("x-kong-trust") == KONG_TRUST_SECRET:
        return True, None
    if any(h in headers for h in _KONG_MARKERS):
        return True, None
    return False, "request did not arrive through the registered Kong route"


def assert_registered_tools(served: list[str], registered: list[str]) -> None:
    """Raise if the live tool set differs from the frozen blueprint (tool-poisoning guard)."""
    served_set, registered_set = set(served), set(registered)
    if served_set != registered_set:
        extra = sorted(served_set - registered_set)
        missing = sorted(registered_set - served_set)
        raise RuntimeError(
            f"tool-trust violation: served tools do not match the registered blueprint "
            f"(unexpected={extra}, missing={missing})")
