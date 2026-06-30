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
load_dotenv(override=True)

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from prompts import SYNTHESIS_PROMPT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MCP server URLs — Kong routes (Mode B: full path through gateway).
# Falls back to host.docker.internal for local dev without Kong.
# ---------------------------------------------------------------------------
VITALS_URL = os.environ.get(
    "VITALS_MCP_URL", "http://localhost:8000/mcp/clinical/vitals-trends/dev"
)
LABS_URL = os.environ.get(
    "LABS_MCP_URL", "http://localhost:8000/mcp/clinical/labs-diagnoses/dev"
)
MEDS_URL = os.environ.get(
    "MEDS_MCP_URL", "http://localhost:8000/mcp/clinical/medications-interactions/dev"
)
NOTES_URL = os.environ.get(
    "NOTES_MCP_URL", "http://localhost:8000/mcp/clinical/clinical-notes-search/dev"
)

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
}


def _registry_service_token() -> str:
    import httpx
    r = httpx.post(f"{KEYCLOAK_ISSUER}/protocol/openid-connect/token",
                   data={"grant_type": "client_credentials",
                         "client_id": KEYCLOAK_CLIENT_ID, "client_secret": KEYCLOAK_CLIENT_SECRET},
                   timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def resolve_server_urls() -> dict[str, str]:
    """{domain: mcp_url}. From registry-api when REGISTRY_DISCOVERY, else static env."""
    if not REGISTRY_DISCOVERY:
        return dict(_STATIC_URLS)
    try:
        import httpx
        token = _registry_service_token()
        r = httpx.get(f"{REGISTRY_URL}/servers",
                      headers={"Authorization": f"Bearer {token}"}, timeout=5)
        r.raise_for_status()
        urls: dict[str, str] = {}
        for s in r.json():
            domain = s.get("domain")
            if not domain:
                continue
            if DISCOVERY_VIA == "kong" and s.get("kong_route"):
                urls[domain] = f"{KONG_BASE}{s['kong_route']}"
            elif s.get("port"):
                urls[domain] = f"http://localhost:{s['port']}/mcp"
        if urls:
            logging.getLogger("runtime-agent").info(
                "registry discovery: %d servers %s", len(urls), sorted(urls))
            return urls
    except Exception as exc:
        logging.getLogger("runtime-agent").warning(
            "registry discovery failed (%s) — falling back to static URLs", exc)
    return dict(_STATIC_URLS)


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

    # RBAC matrix from PRD §6.3
    # clinical-viewer: vitals + labs only
    # physician: all 4
    # case-manager: notes only
    is_physician       = "grp-physician" in (groups or [])
    is_case_manager    = "grp-case-manager" in (groups or [])
    is_clinical_viewer = "grp-clinical-viewer" in (groups or [])

    # URL source: registry-api discovery (opt-in) or static env — same RBAC filtering either way
    urls = resolve_server_urls()
    servers = {}

    def _add(domain: str, allowed: bool) -> None:
        if allowed and urls.get(domain):
            servers[domain] = {"url": urls[domain], "transport": "streamable_http", "headers": headers}

    _add("vitals_trends", is_physician or is_clinical_viewer)
    _add("labs_diagnoses", is_physician or is_clinical_viewer)
    _add("medications_interactions", is_physician)
    _add("clinical_notes_search", is_physician or is_case_manager)

    # fallback — if no groups matched, connect to all (anonymous/POC)
    if not servers:
        for name, url in [
            ("vitals_trends", VITALS_URL),
            ("labs_diagnoses", LABS_URL),
            ("medications_interactions", MEDS_URL),
            ("clinical_notes_search", NOTES_URL),
        ]:
            servers[name] = {
                "url": url,
                "transport": "streamable_http",
                "headers": headers,
            }

    return servers


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

        client = MultiServerMCPClient(server_config)

        try:
            tools = await client.get_tools()
        except BaseException as e:
            logger.warning("Failed to get tools from some servers: %s", e)
            return (
                "Partial answer only — some servers were not accessible for this role "
                "(access denied). Use a physician token for full access.",
                list(server_config.keys()),
            )

        servers_called = list(server_config.keys())

        agent = create_react_agent(
            llm,
            tools,
            state_modifier=SYNTHESIS_PROMPT,
        )

        try:
            result = await agent.ainvoke(
                {"messages": [("human", full_question)]},
            )
            messages = result.get("messages", [])
            if messages:
                return messages[-1].content, servers_called
            return "No answer could be synthesized.", servers_called

        except BaseException as inner_exc:
            error_str = str(inner_exc)
            logger.warning("Agent inner error (likely 403): %s", error_str)
            return (
                "Partial answer only — some servers were not accessible for this role "
                "(access denied). Use a physician token for full access.",
                servers_called,
            )

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

    # --- purpose_of_access enum validation ---
    if request.purpose_of_access not in VALID_PURPOSES:
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
            purpose=request.purpose_of_access,
            token=token,
        )
        return AskResponse(
            answer=answer,
            patient_id=request.patient_id,
            patient_uuid=patient_uuid,
            purpose_of_access=request.purpose_of_access,
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
