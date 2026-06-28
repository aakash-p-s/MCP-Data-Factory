"""labs_diagnoses — MCP server (Codebase PRD §5.4). DB-backed.

Contract (§6.2 / §6.5):
    tools : get_lab_trend, get_active_diagnoses, get_diagnosis_history
    scope : mcp.labs.read
    route : /mcp/clinical/labs-diagnoses/dev   (Kong; direct MCP endpoint is /mcp)
    ok    : FHIR R4 Observation (labs) / Condition (diagnoses)
    deny  : HTTP 403 {"error":{"code":"forbidden","reason":"missing scope mcp.labs.read"}}

RBAC (§6.3): clinical-viewer + physician allow, case-manager deny. Interim group check
mirrors vitals_trends; the shared engine lands in backend/shared/auth.py (Jul 2).

Run:  uv run python backend/servers/labs_diagnoses/main.py   # -> http://localhost:8002/mcp
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import jwt
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backend.connectors.sql_connector import SQLConnector  # noqa: E402
from backend.servers.labs_diagnoses import tools  # noqa: E402

PORT = int(os.getenv("LABS_PORT", "8002"))
REQUIRED_SCOPE = "mcp.labs.read"
ALLOWED_GROUPS = {g.strip() for g in os.getenv(
    "LABS_ALLOWED_GROUPS", "grp-clinical-viewer,grp-physician").split(",") if g.strip()}
CLINICAL_DB_URL = os.environ.get(
    "CLINICAL_DB_URL", "postgresql://postgres:changeme@localhost:5434/clinical")

_default_hosts = [f"localhost:{PORT}", f"127.0.0.1:{PORT}", f"host.docker.internal:{PORT}",
                  "localhost", "127.0.0.1", "host.docker.internal"]
_extra_hosts = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()]
_transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=_default_hosts + _extra_hosts,
    allowed_origins=["*"],
)

mcp = FastMCP("labs_diagnoses", stateless_http=True, transport_security=_transport_security)
_conn = SQLConnector(CLINICAL_DB_URL)


# --- tools (DB-backed via SQLConnector) --------------------------------------
@mcp.tool()
async def get_lab_trend(patient_id: str, test_name: str | None = None) -> list[dict]:
    """Lab result Observations for a patient (live), optionally filtered by test name."""
    return await tools.get_lab_trend(_conn, patient_id, test_name)


@mcp.tool()
async def get_active_diagnoses(patient_id: str) -> list[dict]:
    """Currently-active diagnoses as FHIR Condition resources (live)."""
    return await tools.get_active_diagnoses(_conn, patient_id)


@mcp.tool()
async def get_diagnosis_history(patient_id: str) -> list[dict]:
    """Full diagnosis history (active + resolved) as Condition resources, by onset date."""
    return await tools.get_diagnosis_history(_conn, patient_id)


# --- Layer-2 scope + group guard (ASGI; exact 403 envelope) ------------------
def _service_info(port: int) -> dict:
    return {
        "service": "labs_diagnoses", "status": "ok", "stub": False,
        "mcp_endpoint": f"http://localhost:{port}/mcp", "transport": "streamable-http",
        "scope": REQUIRED_SCOPE, "kong_route": "/mcp/clinical/labs-diagnoses/dev",
        "tools": ["get_lab_trend", "get_active_diagnoses", "get_diagnosis_history"],
        "client_headers": {"Accept": "application/json, text/event-stream",
                           "Content-Type": "application/json"},
        "note": "MCP tool calls require an MCP client. Open / or /health for this summary.",
    }


async def _json_response(send, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class ScopeGuard:
    """Bearer token: must have REQUIRED_SCOPE in `scp` and (if it carries groups) a group
    in ALLOWED_GROUPS — else 403. No token -> allowed (POC). auth.py (Jul 2) supersedes."""

    def __init__(self, app, required_scope: str, port: int, allowed_groups: set[str]):
        self.app, self.required, self.port, self.allowed_groups = app, required_scope, port, allowed_groups

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            headers = dict(scope.get("headers", []))
            accept = headers.get(b"accept", b"").decode().lower()
            if path in ("/", "/health"):
                await _json_response(send, 200, _service_info(self.port)); return
            if path == "/mcp" and "text/event-stream" not in accept:
                await _json_response(send, 200, _service_info(self.port)); return
            auth = headers.get(b"authorization", b"").decode()
            if auth.lower().startswith("bearer "):
                try:
                    claims = jwt.decode(auth[7:], options={"verify_signature": False})
                except Exception:
                    claims = {}
                if self.required not in (claims.get("scp") or "").split():
                    await _json_response(send, 403, {"error": {"code": "forbidden",
                        "reason": f"missing scope {self.required}"}}); return
                token_groups = {g.lstrip("/") for g in (claims.get("groups") or [])}
                if self.allowed_groups and token_groups and not (token_groups & self.allowed_groups):
                    await _json_response(send, 403, {"error": {"code": "forbidden",
                        "reason": f"role not permitted for labs_diagnoses; requires group in {sorted(self.allowed_groups)}"}}); return
        await self.app(scope, receive, send)


app = ScopeGuard(mcp.streamable_http_app(), REQUIRED_SCOPE, PORT, ALLOWED_GROUPS)


if __name__ == "__main__":
    from importlib.metadata import PackageNotFoundError, version

    import uvicorn
    try:
        mcp_version = version("mcp")
    except PackageNotFoundError:
        mcp_version = "unknown"
    print(f"[labs_diagnoses] DB-backed | MCP SDK {mcp_version} "
          f"| health http://localhost:{PORT}/ | mcp http://localhost:{PORT}/mcp "
          f"| scope={REQUIRED_SCOPE} | route=/mcp/clinical/labs-diagnoses/dev", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
