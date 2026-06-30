"""radiology_reports — MCP server (GENERATED from blueprint by onboarding_agent/generate.py).
DB-backed + Fixed Core. Review the generated tools.py before production use.

    tools : ['get_radiology_report_trend', 'get_latest_radiology_report', 'search_radiology_reports_by_modality']
    scope : mcp.radiology.read
    route : /mcp/clinical/radiology-reports/dev
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
from backend.servers.radiology_reports import tools  # noqa: E402

SERVICE = "radiology_reports"
PORT = int(os.getenv("RADIOLOGY_REPORTS_PORT", "8005"))
REQUIRED_SCOPE = "mcp.radiology.read"
ALLOWED_GROUPS = {g.strip() for g in os.getenv(
    "RADIOLOGY_REPORTS_ALLOWED_GROUPS", "grp-physician").split(",") if g.strip()}
KONG_ROUTE = "/mcp/clinical/radiology-reports/dev"
TOOL_NAMES = ['get_radiology_report_trend', 'get_latest_radiology_report', 'search_radiology_reports_by_modality']

mcp = FastMCP(SERVICE, stateless_http=True, transport_security=transport_security(PORT))
_conn = locked_connector_for(SERVICE)


@mcp.tool()
async def get_radiology_report_trend(patient_id: str) -> list[dict]:
    """get_radiology_report_trend (GENERATED stub — queries radiology_reports by patient_id)."""
    result = await tools.get_radiology_report_trend(_conn, patient_id)
    audit_phi("get_radiology_report_trend", patient_id)
    return result


@mcp.tool()
async def get_latest_radiology_report(patient_id: str) -> list[dict]:
    """get_latest_radiology_report (GENERATED stub — queries radiology_reports by patient_id)."""
    result = await tools.get_latest_radiology_report(_conn, patient_id)
    audit_phi("get_latest_radiology_report", patient_id)
    return result


@mcp.tool()
async def search_radiology_reports_by_modality(patient_id: str) -> list[dict]:
    """search_radiology_reports_by_modality (GENERATED stub — queries radiology_reports by patient_id)."""
    result = await tools.search_radiology_reports_by_modality(_conn, patient_id)
    audit_phi("search_radiology_reports_by_modality", patient_id)
    return result


app = FixedCoreGuard(
    mcp.streamable_http_app(), service=SERVICE, required_scope=REQUIRED_SCOPE,
    allowed_groups=ALLOWED_GROUPS, port=PORT, kong_route=KONG_ROUTE, tools=TOOL_NAMES)


if __name__ == "__main__":
    from importlib.metadata import PackageNotFoundError, version

    import uvicorn
    try:
        mcp_version = version("mcp")
    except PackageNotFoundError:
        mcp_version = "unknown"
    print(f"[{SERVICE}] GENERATED | Fixed Core | MCP SDK {mcp_version} "
          f"| health http://localhost:{PORT}/ | mcp http://localhost:{PORT}/mcp "
          f"| scope={REQUIRED_SCOPE} | route={KONG_ROUTE}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
