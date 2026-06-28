"""medications_interactions — MCP server (Codebase PRD §5.4). DB-backed + Fixed Core (Jul 2).

Contract (§6.2 / §6.5):
    tools : get_active_medications, check_drug_interactions, get_polypharmacy_risk
    scope : mcp.meds.read
    route : /mcp/clinical/medications-interactions/dev
    ok    : FHIR R4 MedicationStatement / interaction + polypharmacy dicts
    deny  : HTTP 403 {"error":{"code":"forbidden","reason":"..."}}

RBAC (§6.3): physician-only — clinical-viewer + case-manager denied.

Run:  uv run python backend/servers/medications_interactions/main.py   # -> :8003/mcp
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
from backend.servers.medications_interactions import tools  # noqa: E402

SERVICE = "medications_interactions"
PORT = int(os.getenv("MEDS_PORT", "8003"))
REQUIRED_SCOPE = "mcp.meds.read"
ALLOWED_GROUPS = {g.strip() for g in os.getenv(
    "MEDS_ALLOWED_GROUPS", "grp-physician").split(",") if g.strip()}
KONG_ROUTE = "/mcp/clinical/medications-interactions/dev"
TOOL_NAMES = ["get_active_medications", "check_drug_interactions", "get_polypharmacy_risk"]

mcp = FastMCP(SERVICE, stateless_http=True, transport_security=transport_security(PORT))
_conn = locked_connector_for(SERVICE)


@mcp.tool()
async def get_active_medications(patient_id: str) -> list[dict]:
    """Active medications as FHIR MedicationStatement (one per distinct drug, live)."""
    result = await tools.get_active_medications(_conn, patient_id)
    audit_phi("get_active_medications", patient_id)
    return result


@mcp.tool()
async def check_drug_interactions(patient_id: str) -> list[dict]:
    """Pairwise interactions among active meds (curated RxNorm rule set — illustrative)."""
    result = await tools.check_drug_interactions(_conn, patient_id)
    audit_phi("check_drug_interactions", patient_id)
    return result


@mcp.tool()
async def get_polypharmacy_risk(patient_id: str) -> dict:
    """Polypharmacy risk flag: 5+ distinct active medications = elevated."""
    result = await tools.get_polypharmacy_risk(_conn, patient_id)
    audit_phi("get_polypharmacy_risk", patient_id)
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
