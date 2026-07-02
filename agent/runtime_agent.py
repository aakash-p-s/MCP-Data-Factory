"""
agent/runtime_agent.py

Runtime Agent — LangGraph MCP Host (Codebase PRD §5.7 / Person B PRD §5.5).

Holds 4 MCP Clients (one per server), attaches the caller's Bearer token to
every MCP request, calls all relevant tools in parallel, and fuses results
into one cited answer via the LLM.

Kong URLs are used for all 4 servers (PRD: "Agent runtime path uses Kong URLs").
Demo patient aliases are resolved here (PRD: "resolve aliases from
demo_patient_aliases.json in the agent layer").

Run:  uvicorn runtime_agent:app --host 0.0.0.0 --port 8500
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
# override=False so real env (Docker Compose / shell) wins over the .env file —
# lets the deployment environment pick the right URLs without hand-editing .env.
load_dotenv(override=False)

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from prompts import SYNTHESIS_PROMPT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MCP server URLs. Default = DIRECT to each server on the host (works out of the box for
# a host-run agent). For the full gateway path set the *_MCP_URL envs to Kong routes, or
# use registry discovery with DISCOVERY_VIA=kong. Docker Compose injects host.docker.internal.
# ---------------------------------------------------------------------------
VITALS_URL = os.environ.get("VITALS_MCP_URL", "http://localhost:8001/mcp")
LABS_URL = os.environ.get("LABS_MCP_URL", "http://localhost:8002/mcp")
MEDS_URL = os.environ.get("MEDS_MCP_URL", "http://localhost:8003/mcp")
NOTES_URL = os.environ.get("NOTES_MCP_URL", "http://localhost:8004/mcp")
RADIOLOGY_URL = os.environ.get("RADIOLOGY_MCP_URL", "http://localhost:8005/mcp")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# ---------------------------------------------------------------------------
# Registry-driven discovery (opt-in) — the onboarding→runtime bridge.
# When REGISTRY_DISCOVERY=true the agent reads its server list from registry-api
# (GET /servers) instead of the static URLs above, so a newly onboarded+registered
# domain appears automatically. Uses the agent's OWN Keycloak service identity for
# the registry (an infra call), distinct from the user token forwarded to the servers.
# Falls back to the static URLs on any registry error.
# ---------------------------------------------------------------------------
REGISTRY_DISCOVERY = os.environ.get("REGISTRY_DISCOVERY", "false").lower() in ("1", "true", "yes")
REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://localhost:8600")
DISCOVERY_VIA = os.environ.get("DISCOVERY_VIA", "direct")   # "direct" (port) or "kong"
KONG_BASE = os.environ.get("KONG_BASE", "http://localhost:8000")
KEYCLOAK_ISSUER = os.environ.get("KEYCLOAK_ISSUER", "http://localhost:8080/realms/patient-risk")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "patient-risk-agent")
KEYCLOAK_CLIENT_SECRET = os.environ.get("KEYCLOAK_CLIENT_SECRET", "agent-secret-change-in-prod")

_STATIC_URLS = {
    "vitals_trends": VITALS_URL,
    "labs_diagnoses": LABS_URL,
    "medications_interactions": MEDS_URL,
    "clinical_notes_search": NOTES_URL,
    "radiology_reports": RADIOLOGY_URL,
}
# Frozen RBAC matrix (§6.3) used as the fallback when registry discovery is off.
# Group form (grp-<role>) to match the caller's Keycloak `groups` and the registry's
# rbac_mappings.role_name directly — no name juggling.
_STATIC_RBAC = {
    "vitals_trends": {"grp-clinical-viewer", "grp-physician"},
    "labs_diagnoses": {"grp-clinical-viewer", "grp-physician"},
    "medications_interactions": {"grp-physician"},
    "clinical_notes_search": {"grp-physician", "grp-case-manager"},
    "radiology_reports": {"grp-physician"},
}


def _registry_service_token() -> str:
    import httpx
    r = httpx.post(f"{KEYCLOAK_ISSUER}/protocol/openid-connect/token",
                   data={"grant_type": "client_credentials",
                         "client_id": KEYCLOAK_CLIENT_ID, "client_secret": KEYCLOAK_CLIENT_SECRET},
                   timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def discover_servers() -> dict[str, dict]:
    """{domain: {"url":..., "allowed_roles": set}}. From registry-api when
    REGISTRY_DISCOVERY (URL + RBAC both live), else the static URLs + frozen matrix."""
    if REGISTRY_DISCOVERY:
        try:
            import httpx
            token = _registry_service_token()
            r = httpx.get(f"{REGISTRY_URL}/servers",
                          headers={"Authorization": f"Bearer {token}"}, timeout=5)
            r.raise_for_status()
            out: dict[str, dict] = {}
            for s in r.json():
                domain = s.get("domain")
                if not domain:
                    continue
                if DISCOVERY_VIA == "kong" and s.get("kong_route"):
                    url = f"{KONG_BASE}{s['kong_route']}"
                elif s.get("port"):
                    url = f"http://localhost:{s['port']}/mcp"
                else:
                    continue
                out[domain] = {"url": url, "allowed_roles": set(s.get("allowed_roles") or [])}
            if out:
                logging.getLogger("runtime-agent").info(
                    "registry discovery: %d servers %s", len(out), sorted(out))
                return out
        except Exception as exc:
            logging.getLogger("runtime-agent").warning(
                "registry discovery failed (%s) — falling back to static", exc)
    return {d: {"url": u, "allowed_roles": set(_STATIC_RBAC.get(d, set()))}
            for d, u in _STATIC_URLS.items()}


def resolve_server_urls() -> dict[str, str]:
    """Thin {domain: url} view of discover_servers() (kept for callers/tests)."""
    return {d: info["url"] for d, info in discover_servers().items()}


# ---------------------------------------------------------------------------
# Demo patient alias resolution (PRD: agent layer resolves aliases → UUIDs)
# ---------------------------------------------------------------------------
_ALIASES_PATH = Path(__file__).resolve().parent.parent / \
    "infra" / "synthea" / "demo_patient_aliases.json"

_ALIASES: dict[str, str] = {}
if _ALIASES_PATH.exists():
    try:
        _ALIASES = json.loads(_ALIASES_PATH.read_text())
    except Exception:
        pass


def resolve_patient_id(patient_id: str) -> str:
    """Resolve a friendly alias (demo-patient-1) to the real Synthea UUID."""
    return _ALIASES.get(patient_id, patient_id)


# ---------------------------------------------------------------------------
# Valid purpose_of_access enum (Codebase PRD §6.4 / audit.py)
# ---------------------------------------------------------------------------
VALID_PURPOSES = {
    "deterioration_review",
    "medication_reconciliation",
    "discharge_planning",
    "care_coordination",
    "routine_review",
}

# Common typos / shorthand → canonical enum (QUICK_TEST pitfall #1)
PURPOSE_ALIASES = {
    "medication_review": "medication_reconciliation",
    "meds_review": "medication_reconciliation",
    "med_review": "medication_reconciliation",
}


def normalize_purpose(purpose: str) -> str:
    """Map common purpose typos to the canonical PRD enum."""
    p = purpose.strip()
    return PURPOSE_ALIASES.get(p, p)

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    question: str
    patient_id: str
    purpose_of_access: str = "routine_review"


class AskResponse(BaseModel):
    answer: str
    patient_id: str
    patient_uuid: str
    purpose_of_access: str
    servers_called: list[str]


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Patient Risk Intelligence — Runtime Agent",
    version="1.0.0",
    description=(
        "LangGraph MCP Host. Calls all 4 MCP servers via Kong, "
        "fuses results into one cited clinical risk answer."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def _build_server_config(token: str, groups: list[str] | None = None) -> dict:
    """
    Build MultiServerMCPClient config with Bearer token.
    Only include servers the role can actually access — prevents
    ExceptionGroup crashes when restricted servers deny the token.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    # RBAC is now data-driven: discover_servers() yields each server's url + allowed_roles
    # (from registry-api when REGISTRY_DISCOVERY, else the frozen §6.3 matrix). A server is
    # included only if the caller's roles intersect its allowed_roles — so a newly
    # onboarded+registered domain is auto-callable for the roles its blueprint allows.
    caller_groups = set(groups or [])
    servers = {}
    for domain, info in discover_servers().items():
        if info.get("url") and caller_groups & info.get("allowed_roles", set()):
            servers[domain] = {"url": info["url"], "transport": "streamable_http", "headers": headers}

    # fallback — no groups on the token (anonymous/POC service account): connect to all known
    if not servers and not caller_groups:
        for domain, info in discover_servers().items():
            if info.get("url"):
                servers[domain] = {"url": info["url"], "transport": "streamable_http", "headers": headers}

    return servers


def _rbac_excluded_domains(groups: list[str]) -> list[str]:
    """Domains the caller's groups cannot reach (for clearer /ask errors)."""
    caller_groups = set(groups)
    excluded: list[str] = []
    for domain, info in discover_servers().items():
        if not info.get("url"):
            continue
        allowed = info.get("allowed_roles") or set()
        if caller_groups and not (caller_groups & allowed):
            excluded.append(domain)
    return sorted(excluded)


async def _run_agent(
    question: str,
    patient_uuid: str,
    purpose: str,
    token: str,
) -> tuple[str, list[str]]:
    """
    Core agent logic — connects to all 4 MCP servers, calls tools, fuses answer.
    Returns (answer_text, list_of_servers_successfully_called).
    """
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from langchain_openai import ChatOpenAI
        from langgraph.prebuilt import create_react_agent
    except ImportError as exc:
        raise RuntimeError(
            f"Agent dependencies not installed: {exc}. "
            "Run: pip install langchain-mcp-adapters langgraph langchain-openai"
        ) from exc

    servers_called: list[str] = []

    # Decode token to extract groups for RBAC-aware server selection
    try:
        import jwt as pyjwt
        claims = pyjwt.decode(token, options={"verify_signature": False})
        groups = claims.get("groups", [])
    except Exception:
        groups = []

    server_config = _build_server_config(token, groups)

    if not server_config and groups:
        excluded = _rbac_excluded_domains(groups)
        roles = ", ".join(sorted(groups))
        domains = ", ".join(excluded) or "all registered domains"
        return (
            f"No MCP servers are accessible for your role ({roles}). "
            f"Access denied for: {domains}. "
            "Use a physician token (doctor-test / test123) for medications, notes, and radiology.",
            [],
        )

    full_question = (
        f"{question}\n\n"
        f"Patient ID (UUID): {patient_uuid}\n"
        f"Purpose of access: {purpose}\n\n"
        "IMPORTANT: Cite which server each fact came from in parentheses "
        "— e.g. (vitals_trends) or (medications_interactions). "
        "If a server denied access with 403, say so explicitly — do not retry. "
        "Always produce a complete answer from whatever data is available."
    )

    try:
        llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0,
            openai_api_key=OPENAI_API_KEY,
        )

        # Connect to each server individually — skip any that fail so one
        # unreachable server never silences the rest.
        tools: list = []
        servers_called = []
        for domain, cfg in server_config.items():
            try:
                single_client = MultiServerMCPClient({domain: cfg})
                domain_tools = await single_client.get_tools()
                tools.extend(domain_tools)
                servers_called.append(domain)
            except Exception as e:
                logger.warning("Skipping %s — could not get tools: %s", domain, e)

        if not tools:
            return (
                "No MCP servers responded. Check that all servers are running on :8001–8005.",
                [],
            )

        agent = create_react_agent(
            llm,
            tools,
            state_modifier=SYNTHESIS_PROMPT,
        )

        result = await agent.ainvoke(
            {"messages": [("human", full_question)]},
        )
        messages = result.get("messages", [])
        if messages:
            return messages[-1].content, servers_called
        return "No answer could be synthesized.", servers_called

    except BaseException as exc:
        logger.error("Agent error: %s", exc, exc_info=True)
        raise RuntimeError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/ask", response_model=AskResponse, summary="Ask a clinical risk question")
async def ask_question(
    request: AskRequest,
    authorization: str | None = Header(default=None),
):
    """
    Entry point for the frontend chat page.

    Requires:  Authorization: Bearer <keycloak-token>
    Forwards the token to all 4 MCP servers through Kong.

    patient_id may be a friendly alias (demo-patient-1) or a raw UUID.
    purpose_of_access must be one of the 5 fixed enum values (PRD §6.4).
    """
    # --- auth header check ---
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "code": "unauthorized",
                    "reason": "Missing Authorization header — expected 'Bearer <token>'",
                }
            },
        )
    token = authorization.removeprefix("Bearer ").strip()

    # --- purpose_of_access enum validation (accept common aliases) ---
    purpose = normalize_purpose(request.purpose_of_access)
    if purpose not in VALID_PURPOSES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid purpose_of_access '{request.purpose_of_access}'. "
                f"Must be one of: {', '.join(sorted(VALID_PURPOSES))}"
            ),
        )

    # --- resolve patient alias → UUID ---
    patient_uuid = resolve_patient_id(request.patient_id)

    try:
        answer, servers_called = await _run_agent(
            question=request.question,
            patient_uuid=patient_uuid,
            purpose=purpose,
            token=token,
        )
        return AskResponse(
            answer=answer,
            patient_id=request.patient_id,
            patient_uuid=patient_uuid,
            purpose_of_access=purpose,
            servers_called=servers_called,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Unhandled agent error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Agent error: {type(exc).__name__}: {exc}",
        ) from exc


@app.get("/health", include_in_schema=False)
async def health():
    """Health check — used by docker compose and Kong."""
    return {
        "status": "ok",
        "service": "runtime-agent",
        "servers": {
            "vitals_trends": VITALS_URL,
            "labs_diagnoses": LABS_URL,
            "medications_interactions": MEDS_URL,
            "clinical_notes_search": NOTES_URL,
            "radiology_reports": RADIOLOGY_URL,
        },
        "demo_aliases_loaded": len(_ALIASES),
    }


@app.get("/aliases", include_in_schema=False)
async def list_aliases():
    """Return the demo patient alias map (for debugging)."""
    return _ALIASES


if __name__ == "__main__":
    import uvicorn

    print(
        "[runtime-agent] LangGraph MCP Host | /ask :8500 | "
        f"4 servers via Kong | {len(_ALIASES)} demo aliases loaded",
        flush=True,
    )
    uvicorn.run(app, host="0.0.0.0", port=8500)
