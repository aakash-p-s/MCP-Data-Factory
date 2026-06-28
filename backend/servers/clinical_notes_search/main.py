"""clinical_notes_search — MCP server (Codebase PRD §5.4). Qdrant-backed + Fixed Core.

Contract (§6.2 / §6.5):
    tools : semantic_search_notes, get_recent_notes, get_notes_by_type
    scope : mcp.notes.read
    route : /mcp/clinical/clinical-notes-search/dev
    ok    : FHIR R4 DocumentReference JSON
    deny  : HTTP 403 {"error":{"code":"forbidden","reason":"..."}}

RBAC (§6.3): physician + case-manager allow; clinical-viewer deny.

Requires Qdrant populated (LOAD_NOTES=true when running load_patients.py).

Run:  uv run python backend/servers/clinical_notes_search/main.py   # -> :8004/mcp
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backend.shared.audit import audit_phi  # noqa: E402
from backend.shared.egress_guard import locked_connector_for  # noqa: E402
from backend.shared.middleware import FixedCoreGuard, transport_security  # noqa: E402
from backend.servers.clinical_notes_search import tools  # noqa: E402

SERVICE = "clinical_notes_search"
PORT = int(os.getenv("NOTES_PORT", "8004"))
REQUIRED_SCOPE = "mcp.notes.read"
ALLOWED_GROUPS = {g.strip() for g in os.getenv(
    "NOTES_ALLOWED_GROUPS", "grp-physician,grp-case-manager").split(",") if g.strip()}
KONG_ROUTE = "/mcp/clinical/clinical-notes-search/dev"
TOOL_NAMES = ["semantic_search_notes", "get_recent_notes", "get_notes_by_type"]

mcp = FastMCP(SERVICE, stateless_http=True, transport_security=transport_security(PORT))
_conn = locked_connector_for(SERVICE)


@mcp.tool()
async def semantic_search_notes(patient_id: str, query: str, limit: int = 5) -> list[dict]:
    """Semantic search over a patient's clinical notes (vector similarity in Qdrant)."""
    result = await tools.semantic_search_notes(_conn, patient_id, query, limit)
    audit_phi("semantic_search_notes", patient_id)
    return result


@mcp.tool()
async def get_recent_notes(patient_id: str, limit: int = 5) -> list[dict]:
    """Most recent clinical notes for a patient, newest note_date first."""
    result = await tools.get_recent_notes(_conn, patient_id, limit)
    audit_phi("get_recent_notes", patient_id)
    return result


@mcp.tool()
async def get_notes_by_type(patient_id: str, note_type: str, limit: int = 10) -> list[dict]:
    """Clinical notes filtered by note_type (e.g. physician_note)."""
    result = await tools.get_notes_by_type(_conn, patient_id, note_type, limit)
    audit_phi("get_notes_by_type", patient_id)
    return result


app = FixedCoreGuard(
    mcp.streamable_http_app(),
    service=SERVICE,
    required_scope=REQUIRED_SCOPE,
    allowed_groups=ALLOWED_GROUPS,
    port=PORT,
    kong_route=KONG_ROUTE,
    tools=TOOL_NAMES,
)


if __name__ == "__main__":
    from importlib.metadata import PackageNotFoundError, version

    import uvicorn

    try:
        mcp_version = version("mcp")
    except PackageNotFoundError:
        mcp_version = "unknown"
    print(f"[{SERVICE}] Fixed Core | Qdrant-backed | MCP SDK {mcp_version} "
          f"| health http://localhost:{PORT}/ "
          f"| mcp http://localhost:{PORT}/mcp "
          f"| scope={REQUIRED_SCOPE} | route={KONG_ROUTE}",
          flush=True)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
