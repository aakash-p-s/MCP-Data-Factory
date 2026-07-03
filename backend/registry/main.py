"""
backend/registry/main.py

Registry API — control-plane source of truth for the platform.
Exposes: GET /servers, GET /servers/{id}/health, GET /audit, POST /servers
All endpoints require a valid Keycloak token (non-anonymous).

PRD reference: Section 5.6
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, delete

from auth import require_valid_token
from models import Base, MCPServer, HealthCheck, AuditEvent, ToolSpec, RBACMapping

DATABASE_URL = os.environ["DATABASE_URL"]

# Live health-check sweep — replaces the old manual-only `register.py --health`. Without
# this, mcp_servers.status is a write-once value set at registration time and never reflects
# reality again; a server that dies afterward still shows "healthy" forever. MCP servers run
# on the HOST (see docker-compose.yml comment), so from inside this container we reach them
# via host.docker.internal, same convention Kong already uses (infra/kong/kong.yml).
HEALTH_CHECK_INTERVAL_SECONDS = int(os.getenv("HEALTH_CHECK_INTERVAL_SECONDS", "20"))
MCP_SERVER_HOST = os.getenv("MCP_SERVER_HOST", "host.docker.internal")

logger = logging.getLogger("registry.health")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

app = FastAPI(
    title="Patient Risk Intelligence — Registry API",
    version="1.0.0",
    description="Control-plane source of truth. All endpoints require a valid Keycloak token."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def _check_one(client: httpx.AsyncClient, port: int) -> tuple[str, int, str | None]:
    """Ping one MCP server's /health. Returns (status, latency_ms, error_msg)."""
    start = time.perf_counter()
    try:
        r = await client.get(f"http://{MCP_SERVER_HOST}:{port}/health", timeout=3)
        latency_ms = int((time.perf_counter() - start) * 1000)
        if r.status_code == 200:
            return "healthy", latency_ms, None
        return "unhealthy", latency_ms, f"HTTP {r.status_code}"
    except Exception as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        return "unhealthy", latency_ms, str(exc)[:200]


async def _health_sweep_once() -> None:
    async with AsyncSessionLocal() as db, httpx.AsyncClient() as client:
        servers = (await db.execute(select(MCPServer))).scalars().all()
        for s in servers:
            if not s.port:
                continue
            status, latency_ms, error_msg = await _check_one(client, s.port)
            s.status = status
            s.updated_at = datetime.now(timezone.utc)
            db.add(HealthCheck(server_id=s.server_id, status=status,
                                latency_ms=latency_ms, error_msg=error_msg))
        await db.commit()


async def _health_check_loop() -> None:
    """Background sweep — keeps mcp_servers.status (what the dashboard's colored badge
    reads) truthful without anyone having to remember to run register.py --health."""
    while True:
        try:
            await _health_sweep_once()
        except Exception:
            logger.exception("health sweep failed — will retry next interval")
        await asyncio.sleep(HEALTH_CHECK_INTERVAL_SECONDS)


@app.on_event("startup")
async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.on_event("startup")
async def start_health_sweep():
    asyncio.create_task(_health_check_loop())


@app.get("/servers", summary="List all registered MCP servers")
async def list_servers(
    claims: dict = Depends(require_valid_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns every registered MCP server with its current status and Kong route.
    Used by: Tremor dashboard RegistryTable, Runtime Agent discovery.
    """
    result = await db.execute(select(MCPServer))
    servers = result.scalars().all()
    # aggregate per-server RBAC from rbac_mappings (joined via tool_specs)
    rbac_rows = (await db.execute(
        select(ToolSpec.server_id, RBACMapping.role_name, RBACMapping.required_scope)
        .join(RBACMapping, RBACMapping.tool_id == ToolSpec.tool_id)
        .where(RBACMapping.allowed.is_(True))
    )).all()
    roles_by_server: dict[int, set] = {}
    scope_by_server: dict[int, str] = {}
    for server_id, role_name, scope in rbac_rows:
        roles_by_server.setdefault(server_id, set()).add(role_name)
        if scope:
            scope_by_server[server_id] = scope
    return [
        {
            "server_id":     s.server_id,
            "server_name":   s.server_name,
            "domain":        s.domain,
            "status":        s.status,
            "kong_route":    s.kong_route,
            "port":          s.port,
            "scope":         scope_by_server.get(s.server_id),
            "allowed_roles": sorted(roles_by_server.get(s.server_id, [])),
            "updated_at":    s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in servers
    ]


@app.get("/servers/{server_id}/health", summary="Latest health check for a server")
async def get_server_health(
    server_id: int,
    claims: dict = Depends(require_valid_token),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(HealthCheck)
        .where(HealthCheck.server_id == server_id)
        .order_by(HealthCheck.checked_at.desc())
        .limit(1)
    )
    check = result.scalar_one_or_none()
    if not check:
        raise HTTPException(status_code=404, detail="No health checks found for this server")
    return {
        "server_id":  server_id,
        "status":     check.status,
        "checked_at": check.checked_at.isoformat(),
        "latency_ms": check.latency_ms,
        "error_msg":  check.error_msg,
    }


@app.get("/servers/{server_id}/tools", summary="Cached tool schemas for a server")
async def get_server_tools(
    server_id: int,
    claims: dict = Depends(require_valid_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns each tool's cached name/description/input_schema from tool_specs — populated
    at registration time (see backend/onboarding_agent/register.py). Lets the runtime agent
    build a callable tool for the LLM WITHOUT opening a live MCP connection to discover it;
    a domain the LLM never decides to call is never connected to at all.
    """
    result = await db.execute(select(ToolSpec).where(ToolSpec.server_id == server_id))
    tools = result.scalars().all()
    return [
        {
            "name":         t.tool_name,
            "description":  t.description,
            "input_schema": t.input_schema,
        }
        for t in tools
    ]


@app.post("/servers", status_code=201, summary="Register or update an MCP server")
async def register_server(
    payload: dict,
    claims: dict = Depends(require_valid_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Called by the CI/CD pipeline after a successful deployment.
    Creates a new registry entry or updates an existing one.
    """
    server_name = payload.get("server_name")
    if not server_name:
        raise HTTPException(status_code=422, detail="server_name is required")

    result = await db.execute(
        select(MCPServer).where(MCPServer.server_name == server_name)
    )
    server = result.scalar_one_or_none()

    if server:
        server.status     = payload.get("status", "healthy")
        server.kong_route = payload.get("kong_route", server.kong_route)
        server.port       = payload.get("port", server.port)
        server.updated_at = datetime.now(timezone.utc)
    else:
        server = MCPServer(
            server_name = server_name,
            domain      = payload.get("domain", "unknown"),
            status      = payload.get("status", "pending"),
            kong_route  = payload.get("kong_route"),
            port        = payload.get("port"),
        )
        db.add(server)
    await db.flush()   # populate server.server_id

    # Optional: tools + per-role RBAC from the blueprint (the build pipeline passes these).
    # Stored in tool_specs + rbac_mappings so GET /servers can return allowed_roles, and
    # GET /servers/{id}/tools can return cached schemas the runtime agent builds tools from
    # WITHOUT connecting to the live MCP server just to ask it (see agent/runtime_agent.py).
    tools = payload.get("tools") or []
    rbac = payload.get("rbac") or {}            # {role_name: "allow"|"deny"}
    scope = payload.get("scope")
    if tools:
        existing = (await db.execute(
            select(ToolSpec).where(ToolSpec.server_id == server.server_id))).scalars().all()
        for ts in existing:
            await db.execute(delete(RBACMapping).where(RBACMapping.tool_id == ts.tool_id))
            await db.delete(ts)
        await db.flush()
        for t in tools:
            # Accept both the legacy bare-name-string form and the richer dict form
            # (name + input_schema + description) so older callers don't break.
            if isinstance(t, str):
                tname, input_schema, description = t, None, None
            else:
                tname = t.get("name")
                input_schema = t.get("input_schema")
                description = t.get("description")
            if not tname:
                continue
            ts = ToolSpec(server_id=server.server_id, tool_name=tname,
                          input_schema=input_schema, description=description)
            db.add(ts)
            await db.flush()
            for role, decision in rbac.items():
                # rbac_mappings.role_name CHECK requires the group form (grp-<role>)
                role_key = role if role.startswith("grp-") else f"grp-{role}"
                db.add(RBACMapping(tool_id=ts.tool_id, role_name=role_key,
                                   allowed=str(decision).lower() == "allow",
                                   required_scope=scope))

    await db.commit()
    return {"message": f"Server '{server_name}' registered successfully"}


@app.get("/audit", summary="Query audit log, optionally filtered by role")
async def get_audit_log(
    role: str | None = None,
    limit: int = 100,
    claims: dict = Depends(require_valid_token),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns recent audit events.
    Used by Tremor dashboard KPI cards and Grafana PHI anomaly panel.
    """
    query = (
        select(AuditEvent)
        .order_by(AuditEvent.when_ts.desc())
        .limit(limit)
    )
    result = await db.execute(query)
    events = result.scalars().all()
    return [
        {
            "who":               e.who,
            "what":              e.what,
            "when":              e.when_ts.isoformat(),
            "outcome":           e.outcome,
            "reason":            e.reason,
            "purpose_of_access": e.purpose_of_access,
            "trace_id":          e.trace_id,
            "server_name":       e.server_name,
        }
        for e in events
    ]


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}
