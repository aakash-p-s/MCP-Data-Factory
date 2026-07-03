"""Fixed Core ASGI middleware — replaces per-server ScopeGuard (Jul 2).

Layer-2 gate: verify JWT (signature when AUTH_VERIFY_SIGNATURE), enforce scope + group
RBAC via auth.py, audit every auth decision, stash claims in request_context for tool-level
PHI audit. Pure ASGI so MCP streaming responses are never buffered.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable

import jwt

from backend.shared import telemetry, tool_trust, usage_log
from backend.shared.audit import log_call, normalize_purpose
from backend.shared.auth import evaluate, verify_token
from backend.shared.request_context import clear_context, set_context

ALLOW_ANONYMOUS = os.getenv("AUTH_ALLOW_ANONYMOUS", "false").lower() in ("1", "true", "yes")


async def _json_response(send, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})


class FixedCoreGuard:
    """Shared Layer-2 guard for all MCP servers."""

    def __init__(
        self,
        app: Callable,
        *,
        service: str,
        required_scope: str,
        allowed_groups: set[str],
        port: int,
        kong_route: str,
        tools: list[str],
    ):
        self.app = app
        self.service = service
        self.required_scope = required_scope
        self.allowed_groups = allowed_groups
        self.port = port
        self.kong_route = kong_route
        self.tools = tools
        telemetry.configure(service)

    def service_info(self) -> dict:
        return {
            "service": self.service,
            "status": "ok",
            "fixed_core": True,
            "mcp_endpoint": f"http://localhost:{self.port}/mcp",
            "transport": "streamable-http",
            "scope": self.required_scope,
            "kong_route": self.kong_route,
            "tools": self.tools,
            "usage_endpoint": f"http://localhost:{self.port}/usage",
            "client_headers": {
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "X-Purpose-Of-Access": "routine_review (enum; optional)",
            },
            "note": "MCP tool calls require an MCP client. Open / or /health for this summary.",
        }

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        raw_headers = scope.get("headers", [])
        headers = {k.decode().lower(): v.decode() for k, v in raw_headers}
        accept = headers.get("accept", "").lower()

        if path in ("/", "/health"):
            await _json_response(send, 200, self.service_info())
            return

        if path == "/usage":
            await _json_response(send, 200, {
                "service": self.service, "usage": usage_log.snapshot(self.service)})
            return

        if path == "/mcp" and "text/event-stream" not in accept:
            await _json_response(send, 200, self.service_info())
            return

        purpose = normalize_purpose(headers.get("x-purpose-of-access"))
        trace_id = telemetry.extract_trace_id(headers)

        # Tool-trust: a hardened server only answers through its registered Kong route
        # (no-op unless TOOL_TRUST_ENFORCE=true).
        trusted, trust_reason = tool_trust.verify_kong_origin(headers)
        if not trusted:
            usage_log.record("unknown", self.service, "denied")
            log_call("unknown", f"{self.service}:auth", "denied", trust_reason, purpose, trace_id,
                      server_name=self.service)
            with telemetry.span(f"{self.service}.denied", trace_id, outcome="403", reason=trust_reason):
                await _json_response(send, 403, {
                    "error": {"code": "forbidden", "reason": trust_reason},
                })
            return

        auth = headers.get("authorization", "")

        if not auth.lower().startswith("bearer "):
            if ALLOW_ANONYMOUS:
                set_context(None, purpose, trace_id, self.service)
                try:
                    with telemetry.span(f"{self.service}.request", trace_id, role="anonymous"):
                        await self.app(scope, receive, send)
                finally:
                    clear_context()
                return
            usage_log.record("anonymous", self.service, "denied")
            log_call("anonymous", f"{self.service}:auth", "denied",
                     "missing bearer token", purpose, trace_id, server_name=self.service)
            with telemetry.span(f"{self.service}.denied", trace_id, outcome="401",
                                 reason="missing bearer token"):
                await _json_response(send, 401, {
                    "error": {
                        "code": "unauthorized",
                        "reason": "Missing or malformed Authorization header — expected 'Bearer <token>'",
                    },
                })
            return

        token = auth[7:].strip()
        try:
            claims = verify_token(token)
        except jwt.PyJWTError as exc:
            usage_log.record("unknown", self.service, "denied")
            log_call("unknown", f"{self.service}:auth", "denied", str(exc), purpose, trace_id,
                      server_name=self.service)
            with telemetry.span(f"{self.service}.denied", trace_id, outcome="401", reason=str(exc)):
                await _json_response(send, 401, {
                    "error": {"code": "unauthorized", "reason": str(exc)},
                })
            return

        who = str(claims.get("sub") or "unknown")
        role = usage_log.role_of(claims)
        ok, reason = evaluate(claims, self.required_scope, self.allowed_groups, self.service)
        if not ok:
            usage_log.record(role, self.service, "denied")
            log_call(who, f"{self.service}:auth", "denied", reason, purpose, trace_id,
                      server_name=self.service)
            with telemetry.span(f"{self.service}.denied", trace_id, outcome="403", reason=reason,
                                 role=role, who=who):
                await _json_response(send, 403, {
                    "error": {"code": "forbidden", "reason": reason},
                })
            return

        usage_log.record(role, self.service, "allowed")
        log_call(who, f"{self.service}:auth", "allowed", None, purpose, trace_id,
                  server_name=self.service)
        set_context(claims, purpose, trace_id, self.service)
        try:
            with telemetry.span(f"{self.service}.request", trace_id, role=role, who=who):
                await self.app(scope, receive, send)
        finally:
            clear_context()


def transport_security(port: int) -> "TransportSecuritySettings":
    """MCP DNS-rebinding allow-list (Kong forwards host.docker.internal)."""
    from mcp.server.transport_security import TransportSecuritySettings

    default_hosts = [
        f"localhost:{port}", f"127.0.0.1:{port}", f"host.docker.internal:{port}",
        "localhost", "127.0.0.1", "host.docker.internal",
    ]
    extra = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=default_hosts + extra,
        allowed_origins=["*"],
    )
