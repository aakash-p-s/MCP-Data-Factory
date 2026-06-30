"""Generate a runnable MCP server from an approved blueprint.yaml.

This is the missing factory step between the onboarding agent (which writes a blueprint)
and the runtime (which calls the server): it instantiates the hardened template into a
real `backend/servers/<domain>/` package — main.py (Fixed Core), a tools.py stub that
queries the domain's table, Dockerfile, requirements.txt — so a newly onboarded domain
becomes a running, registrable server with no hand-coding.

The generated tools.py is a SCAFFOLD: each tool queries `<table> WHERE patient_id` and
FHIR-shapes the rows. Specialise the queries for production. (The full vision automates
this in CI/CD; here it's a one-command generator.)

  uv run python -m backend.onboarding_agent.generate backend/onboarding_agent/output/radiology_reports.blueprint.yaml
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from backend.onboarding_agent.register import DOMAIN_PORT

REPO_ROOT = Path(__file__).resolve().parents[2]


_MAIN_TEMPLATE = '''"""{domain} — MCP server (GENERATED from blueprint by onboarding_agent/generate.py).
DB-backed + Fixed Core. Review the generated tools.py before production use.

    tools : {tool_names}
    scope : {scope}
    route : {kong_route}
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
from backend.servers.{domain} import tools  # noqa: E402

SERVICE = "{domain}"
PORT = int(os.getenv("{env_prefix}_PORT", "{port}"))
REQUIRED_SCOPE = "{scope}"
ALLOWED_GROUPS = {{g.strip() for g in os.getenv(
    "{env_prefix}_ALLOWED_GROUPS", "{groups_csv}").split(",") if g.strip()}}
KONG_ROUTE = "{kong_route}"
TOOL_NAMES = {tool_names!r}

mcp = FastMCP(SERVICE, stateless_http=True, transport_security=transport_security(PORT))
_conn = locked_connector_for(SERVICE)


{tool_defs}

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
    print(f"[{{SERVICE}}] GENERATED | Fixed Core | MCP SDK {{mcp_version}} "
          f"| health http://localhost:{{PORT}}/ | mcp http://localhost:{{PORT}}/mcp "
          f"| scope={{REQUIRED_SCOPE}} | route={{KONG_ROUTE}}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
'''

_TOOL_DEF = '''@mcp.tool()
async def {name}(patient_id: str) -> list[dict]:
    """{name} (GENERATED stub — queries {table} by patient_id)."""
    result = await tools.{name}(_conn, patient_id)
    audit_phi("{name}", patient_id)
    return result
'''

_TOOLS_TEMPLATE = '''"""{domain} tools — GENERATED stub.

Each tool queries `{table}` by patient_id and wraps rows as FHIR DocumentReference.
Specialise the SQL + FHIR shaping for production.
"""

from __future__ import annotations

from backend.connectors.sql_connector import SQLConnector

TABLE = "{table}"


def _to_resource(row: dict) -> dict:
    data = {{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}}
    return {{
        "resourceType": "DocumentReference",
        "status": "current",
        "subject": {{"reference": f"Patient/{{row.get('patient_id')}}"}},
        "description": row.get("impression") or row.get("description"),
        "content": [{{"attachment": {{"contentType": "application/json"}}}}],
        "data": data,
    }}


async def _query(conn: SQLConnector, patient_id: str) -> list[dict]:
    rows = await conn.query({{"sql": f"SELECT * FROM {{TABLE}} WHERE patient_id = $1 LIMIT 50",
                             "args": [patient_id]}})
    return [_to_resource(r) for r in rows]


{tool_fns}
'''

_TOOL_FN = '''async def {name}(conn: SQLConnector, patient_id: str) -> list[dict]:
    """{name} — GENERATED: returns {table} rows for the patient (specialise me)."""
    return await _query(conn, patient_id)
'''

_DOCKERFILE = '''FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
ENV {env_prefix}_PORT={port}
EXPOSE {port}
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "{port}"]
'''

_REQS = "mcp>=1.27,<2\nfastapi==0.136.*\nuvicorn[standard]\npyjwt\nasyncpg\n"


def _groups_csv(rbac: dict) -> str:
    allowed = [r for r, d in rbac.items() if str(d).lower() == "allow"]
    return ",".join((g if g.startswith("grp-") else f"grp-{g}") for g in allowed)


def generate_server(blueprint_path: str | Path, table: str | None = None) -> Path:
    bp = yaml.safe_load(Path(blueprint_path).read_text())
    domain = bp["domain"]
    table = table or domain
    tool_names = [t["name"] for t in bp.get("tools", []) if t.get("name")]
    env_prefix = re.sub(r"[^A-Z0-9]", "_", domain.upper())
    fields = dict(
        domain=domain, table=table, scope=bp.get("scope", f"mcp.{domain}.read"),
        kong_route=bp.get("kong_route", f"/mcp/clinical/{domain.replace('_','-')}/dev"),
        port=DOMAIN_PORT.get(domain, 8005), env_prefix=env_prefix,
        groups_csv=_groups_csv(bp.get("rbac", {})), tool_names=tool_names,
        tool_defs="\n\n".join(_TOOL_DEF.format(name=n, table=table) for n in tool_names),
    )
    out = REPO_ROOT / "backend" / "servers" / domain
    out.mkdir(parents=True, exist_ok=True)
    (out / "__init__.py").write_text("")
    (out / "main.py").write_text(_MAIN_TEMPLATE.format(**fields))
    (out / "tools.py").write_text(_TOOLS_TEMPLATE.format(
        domain=domain, table=table,
        tool_fns="\n\n".join(_TOOL_FN.format(name=n, table=table) for n in tool_names)))
    (out / "Dockerfile").write_text(_DOCKERFILE.format(env_prefix=env_prefix, port=fields["port"]))
    (out / "requirements.txt").write_text(_REQS)
    (out / "blueprint.yaml").write_text(Path(blueprint_path).read_text())
    print(f"[generate] wrote {out}/  ({len(tool_names)} tools, port {fields['port']}, table {table})")
    print(f"[generate] start it:  uv run python backend/servers/{domain}/main.py")
    return out


def main() -> None:
    if not sys.argv[1:]:
        sys.exit("usage: generate <blueprint.yaml> [table_name]")
    generate_server(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)


if __name__ == "__main__":
    main()
