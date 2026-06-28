"""vitals_trends — MCP server (Codebase PRD §5.4). DB-backed + Fixed Core (Jul 2).

Contract (§6.2 / §6.5):
    tools : get_vitals_trend, compute_news2_score, list_abnormal_vitals
    scope : mcp.vitals.read
    route : /mcp/clinical/vitals-trends/dev
    ok    : FHIR R4 Observation JSON
    deny  : HTTP 403 {"error":{"code":"forbidden","reason":"..."}}

Run:  uv run python backend/servers/vitals_trends/main.py   # -> http://localhost:8001/mcp
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
from backend.servers.vitals_trends import tools  # noqa: E402

SERVICE = "vitals_trends"
PORT = int(os.getenv("VITALS_PORT", "8001"))
REQUIRED_SCOPE = "mcp.vitals.read"
ALLOWED_GROUPS = {g.strip() for g in os.getenv(
    "VITALS_ALLOWED_GROUPS", "grp-clinical-viewer,grp-physician").split(",") if g.strip()}
KONG_ROUTE = "/mcp/clinical/vitals-trends/dev"
TOOL_NAMES = ["get_vitals_trend", "compute_news2_score", "list_abnormal_vitals"]

mcp = FastMCP(SERVICE, stateless_http=True, transport_security=transport_security(PORT))
_conn = locked_connector_for(SERVICE)


@mcp.tool()
async def get_vitals_trend(patient_id: str, hours: int = 24) -> list[dict]:
    """Recent vital-sign Observations for a patient (live TimescaleDB)."""
    result = await tools.get_vitals_trend(_conn, patient_id, hours)
    audit_phi("get_vitals_trend", patient_id)
    return result


@mcp.tool()
async def compute_news2_score(patient_id: str) -> dict:
    """NEWS2 deterioration score + risk band from the latest vitals (NHS algorithm)."""
    result = await tools.compute_news2_score(_conn, patient_id)
    audit_phi("compute_news2_score", patient_id)
    return result


@mcp.tool()
async def list_abnormal_vitals(patient_id: str, hours: int = 24) -> list[dict]:
    """Vital-sign Observations outside the normal range (live), flagged H/L."""
    result = await tools.list_abnormal_vitals(_conn, patient_id, hours)
    audit_phi("list_abnormal_vitals", patient_id)
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
    print(f"[{SERVICE}] Fixed Core | DB-backed | MCP SDK {mcp_version} "
          f"| health http://localhost:{PORT}/ "
          f"| mcp http://localhost:{PORT}/mcp "
          f"| scope={REQUIRED_SCOPE} | route={KONG_ROUTE}",
          flush=True)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
