"""labs_diagnoses — MCP server (Codebase PRD §5.4). DB-backed + Fixed Core (Jul 2).

Contract (§6.2 / §6.5):
    tools : get_lab_trend, get_active_diagnoses, get_diagnosis_history
    scope : mcp.labs.read
    route : /mcp/clinical/labs-diagnoses/dev
    ok    : FHIR R4 Observation (labs) / Condition (diagnoses)
    deny  : HTTP 403 {"error":{"code":"forbidden","reason":"..."}}

Run:  uv run python backend/servers/labs_diagnoses/main.py   # -> http://localhost:8002/mcp
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
from backend.servers.labs_diagnoses import tools  # noqa: E402

SERVICE = "labs_diagnoses"
PORT = int(os.getenv("LABS_PORT", "8002"))
REQUIRED_SCOPE = "mcp.labs.read"
ALLOWED_GROUPS = {g.strip() for g in os.getenv(
    "LABS_ALLOWED_GROUPS", "grp-clinical-viewer,grp-physician").split(",") if g.strip()}
KONG_ROUTE = "/mcp/clinical/labs-diagnoses/dev"
TOOL_NAMES = ["get_lab_trend", "get_active_diagnoses", "get_diagnosis_history"]

mcp = FastMCP(SERVICE, stateless_http=True, transport_security=transport_security(PORT))
_conn = locked_connector_for(SERVICE)


@mcp.tool()
async def get_lab_trend(patient_id: str, test_name: str | None = None) -> list[dict]:
    """Lab result Observations for a patient (live), optionally filtered by test name."""
    result = await tools.get_lab_trend(_conn, patient_id, test_name)
    audit_phi("get_lab_trend", patient_id)
    return result


@mcp.tool()
async def get_active_diagnoses(patient_id: str) -> list[dict]:
    """Currently-active diagnoses as FHIR Condition resources (live)."""
    result = await tools.get_active_diagnoses(_conn, patient_id)
    audit_phi("get_active_diagnoses", patient_id)
    return result


@mcp.tool()
async def get_diagnosis_history(patient_id: str) -> list[dict]:
    """Full diagnosis history (active + resolved) as Condition resources, by onset date."""
    result = await tools.get_diagnosis_history(_conn, patient_id)
    audit_phi("get_diagnosis_history", patient_id)
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
