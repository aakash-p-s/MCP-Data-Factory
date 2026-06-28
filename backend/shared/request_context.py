"""Per-request context for the Fixed Core (auth claims, audit purpose, trace id).

Set by FixedCoreGuard before the MCP app runs; read by tool wrappers for PHI audit.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    claims: dict | None
    purpose_of_access: str
    trace_id: str | None


_ctx: ContextVar[RequestContext | None] = ContextVar("fixed_core_request", default=None)


def set_context(claims: dict | None, purpose_of_access: str, trace_id: str | None) -> None:
    _ctx.set(RequestContext(claims, purpose_of_access, trace_id))


def clear_context() -> None:
    _ctx.set(None)


def get_context() -> RequestContext | None:
    return _ctx.get()


def actor_sub() -> str:
    ctx = get_context()
    if ctx and ctx.claims:
        return str(ctx.claims.get("sub") or "unknown")
    return "anonymous"
