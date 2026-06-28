"""vitals_trends — MCP server (Codebase PRD §5.4). DB-backed as of Jun 29.

The contract is FIXED and UNCHANGED from the Day-1 stub (§6.2 / §6.5):

    tools : get_vitals_trend, compute_news2_score, list_abnormal_vitals
    scope : mcp.vitals.read
    route : /mcp/clinical/vitals-trends/dev   (Kong; direct MCP endpoint is /mcp)
    ok    : FHIR R4 Observation JSON
    deny  : HTTP 403 {"error":{"code":"forbidden","reason":"missing scope mcp.vitals.read"}}

Tools now query live TimescaleDB via SQLConnector (tools.py) and FHIR-shape the rows —
the stub's hardcoded data is gone, but tool names + shapes are identical, so the swap is
invisible to Person B's agent.

Real JWT signature verification + full group/scope RBAC land Jul 2 (backend/shared/auth.py).
For now: a bearer token missing the scope gets the 403 envelope; no token is allowed.

Run:  uv run python backend/servers/vitals_trends/main.py   # -> http://localhost:8001/mcp
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import jwt
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

# repo root on sys.path so `backend.*` imports resolve when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backend.connectors.sql_connector import SQLConnector  # noqa: E402
from backend.servers.vitals_trends import tools  # noqa: E402

PORT = int(os.getenv("VITALS_PORT", "8001"))
REQUIRED_SCOPE = "mcp.vitals.read"
VITALS_DB_URL = os.environ.get(
    "VITALS_DB_URL", "postgresql://postgres:changeme@localhost:5433/vitals")

# MCP DNS-rebinding protection rejects any Host header not in this list. Behind Kong
# the forwarded Host is the upstream (e.g. host.docker.internal:8001), so allow-list the
# known hosts instead of disabling protection. Extra hosts via ALLOWED_HOSTS (comma-sep).
_default_hosts = [f"localhost:{PORT}", f"127.0.0.1:{PORT}", f"host.docker.internal:{PORT}",
                  "localhost", "127.0.0.1", "host.docker.internal"]
_extra_hosts = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]
_transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=_default_hosts + _extra_hosts,
    allowed_origins=["*"],
)

mcp = FastMCP("vitals_trends", stateless_http=True, transport_security=_transport_security)


# connector bound to the vitals DB at construction (egress-guard intent)
_conn = SQLConnector(VITALS_DB_URL)


# --- tools (DB-backed via SQLConnector; SAME names/shape as the Day-1 stub) ----
@mcp.tool()
async def get_vitals_trend(patient_id: str, hours: int = 24) -> list[dict]:
    """Recent vital-sign Observations for a patient (live TimescaleDB)."""
    return await tools.get_vitals_trend(_conn, patient_id, hours)


@mcp.tool()
async def compute_news2_score(patient_id: str) -> dict:
    """NEWS2 deterioration score + risk band from the latest vitals (NHS algorithm)."""
    return await tools.compute_news2_score(_conn, patient_id)


@mcp.tool()
async def list_abnormal_vitals(patient_id: str, hours: int = 24) -> list[dict]:
    """Vital-sign Observations outside the normal range (live), flagged H/L."""
    return await tools.list_abnormal_vitals(_conn, patient_id, hours)


# --- Layer-2 scope guard (ASGI; emits the exact 403 envelope) -----------------
def _service_info(port: int) -> dict:
    return {
        "service": "vitals_trends",
        "status": "ok",
        "stub": False,
        "mcp_endpoint": f"http://localhost:{port}/mcp",
        "transport": "streamable-http",
        "scope": REQUIRED_SCOPE,
        "kong_route": "/mcp/clinical/vitals-trends/dev",
        "tools": [
            "get_vitals_trend",
            "compute_news2_score",
            "list_abnormal_vitals",
        ],
        "client_headers": {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        "note": "MCP tool calls require an MCP client. Open / or /health for this summary.",
    }


async def _json_response(send, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class ScopeGuard:
    """Pure-ASGI guard so it never buffers MCP's streaming responses.

    Stub behavior: a bearer token missing REQUIRED_SCOPE -> 403 envelope.
    No token -> allowed (POC-friendly). Signature verification is added Jul 2.
    Browser / non-MCP probes to /, /health, or /mcp get a readable JSON summary.
    """

    def __init__(self, app, required_scope: str, port: int):
        self.app = app
        self.required = required_scope
        self.port = port

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            headers = dict(scope.get("headers", []))
            accept = headers.get(b"accept", b"").decode().lower()

            if path in ("/", "/health"):
                await _json_response(send, 200, _service_info(self.port))
                return

            if path == "/mcp" and "text/event-stream" not in accept:
                await _json_response(send, 200, _service_info(self.port))
                return

            auth = headers.get(b"authorization", b"").decode()
            if auth.lower().startswith("bearer "):
                try:
                    claims = jwt.decode(auth[7:], options={"verify_signature": False})
                except Exception:
                    claims = {}
                scopes = (claims.get("scp") or "").split()
                if self.required not in scopes:
                    await _json_response(send, 403, {
                        "error": {
                            "code": "forbidden",
                            "reason": f"missing scope {self.required}",
                        },
                    })
                    return
        await self.app(scope, receive, send)


app = ScopeGuard(mcp.streamable_http_app(), REQUIRED_SCOPE, PORT)


if __name__ == "__main__":
    from importlib.metadata import PackageNotFoundError, version

    import uvicorn

    try:
        mcp_version = version("mcp")          # the SDK has no module __version__
    except PackageNotFoundError:
        mcp_version = "unknown"
    print(f"[vitals_trends] DB-backed | MCP SDK {mcp_version} "
          f"| health http://localhost:{PORT}/ "
          f"| mcp http://localhost:{PORT}/mcp "
          f"| scope={REQUIRED_SCOPE} | route=/mcp/clinical/vitals-trends/dev",
          flush=True)   # flush so the banner shows in redirected/Docker logs
    uvicorn.run(app, host="0.0.0.0", port=PORT)
