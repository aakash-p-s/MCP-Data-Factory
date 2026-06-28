"""Shared RBAC matrix fixtures — blueprint §6.3 (4 servers × 3 roles)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import jwt

_SECRET = "x" * 32

# server -> (scope, allowed_groups, app import path)
SERVER_SPECS: dict[str, dict] = {
    "vitals_trends": {
        "scope": "mcp.vitals.read",
        "allowed_groups": {"grp-clinical-viewer", "grp-physician"},
        "tools": ["get_vitals_trend", "compute_news2_score", "list_abnormal_vitals"],
        "module": "backend.servers.vitals_trends.main",
    },
    "labs_diagnoses": {
        "scope": "mcp.labs.read",
        "allowed_groups": {"grp-clinical-viewer", "grp-physician"},
        "tools": ["get_lab_trend", "get_active_diagnoses", "get_diagnosis_history"],
        "module": "backend.servers.labs_diagnoses.main",
    },
    "medications_interactions": {
        "scope": "mcp.meds.read",
        "allowed_groups": {"grp-physician"},
        "tools": ["get_active_medications", "check_drug_interactions", "get_polypharmacy_risk"],
        "module": "backend.servers.medications_interactions.main",
    },
    "clinical_notes_search": {
        "scope": "mcp.notes.read",
        "allowed_groups": {"grp-physician", "grp-case-manager"},
        "tools": ["semantic_search_notes", "get_recent_notes", "get_notes_by_type"],
        "module": "backend.servers.clinical_notes_search.main",
    },
}

SERVER_PORTS: dict[str, int] = {
    "vitals_trends": 8001,
    "labs_diagnoses": 8002,
    "medications_interactions": 8003,
    "clinical_notes_search": 8004,
}

ROLES: dict[str, list[str]] = {
    "clinical-viewer": ["grp-clinical-viewer"],
    "physician": ["grp-physician"],
    "case-manager": ["grp-case-manager"],
}

# PRD / Contract Reference matrix
ACCESS: dict[str, dict[str, bool]] = {
    "clinical-viewer": {
        "vitals_trends": True,
        "labs_diagnoses": True,
        "medications_interactions": False,
        "clinical_notes_search": False,
    },
    "physician": {s: True for s in SERVER_SPECS},
    "case-manager": {
        "vitals_trends": False,
        "labs_diagnoses": False,
        "medications_interactions": False,
        "clinical_notes_search": True,
    },
}

ALL_SCOPES = "mcp.vitals.read mcp.labs.read mcp.meds.read mcp.notes.read"

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}

TOOLS_LIST_BODY = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


def bearer_token(role: str, *, sub: str | None = None) -> str:
    """JWT with all scopes (coarse Keycloak mapper) + role groups."""
    return jwt.encode(
        {
            "sub": sub or f"test-{role}",
            "scp": ALL_SCOPES,
            "groups": ROLES[role],
        },
        _SECRET,
        algorithm="HS256",
    )


def load_app(server: str, *, fresh: bool = False):
    import importlib

    module_path = SERVER_SPECS[server]["module"]
    mod = importlib.import_module(module_path)
    if fresh:
        mod = importlib.reload(mod)
    return mod.app


@contextmanager
def mcp_test_client(server: str) -> Iterator:
    """Starlette TestClient with MCP lifespan + transport-security host allow-list."""
    from starlette.testclient import TestClient

    port = SERVER_PORTS[server]
    app = load_app(server, fresh=True)
    with TestClient(app, base_url=f"http://localhost:{port}") as client:
        yield client


def matrix_cases():
    """Yield (role, server, expect_allow) for parametrized tests."""
    for role, servers in ACCESS.items():
        for server, allowed in servers.items():
            yield role, server, allowed
