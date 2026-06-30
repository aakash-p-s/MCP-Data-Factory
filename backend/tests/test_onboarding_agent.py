"""
backend/tests/test_onboarding_agent.py

Golden-file tests (ONBOARDING_AGENT.md: "the 4 committed blueprints are the
validation oracle — re-deriving one for a known domain proves suggest_tools
+ draft_rbac work").

draft_rbac() is deterministic (not LLM-based) so it is tested directly
against the frozen RBAC matrix for all 4 known domains. suggest_tools() is
LLM-based and only checked for shape (3 tools, patient_id-first signature),
not exact content, since LLM output is not deterministic.
"""

from __future__ import annotations

import pytest

from backend.onboarding_agent.draft_rbac import DOMAIN_SCOPES, ROLE_MATRIX, draft_rbac
from backend.onboarding_agent.suggest_tools import _fallback_tools

# Mirrors each blueprint.yaml's `rbac:` block exactly (Codebase PRD §6.3 / §6.2)
EXPECTED_RBAC = {
    "vitals_trends": {
        "clinical-viewer": "allow",
        "physician": "allow",
        "case-manager": "deny",
    },
    "labs_diagnoses": {
        "clinical-viewer": "allow",
        "physician": "allow",
        "case-manager": "deny",
    },
    "medications_interactions": {
        "clinical-viewer": "deny",
        "physician": "allow",
        "case-manager": "deny",
    },
    "clinical_notes_search": {
        "clinical-viewer": "deny",
        "physician": "allow",
        "case-manager": "allow",
    },
}

EXPECTED_SCOPE = {
    "vitals_trends": "mcp.vitals.read",
    "labs_diagnoses": "mcp.labs.read",
    "medications_interactions": "mcp.meds.read",
    "clinical_notes_search": "mcp.notes.read",
}


@pytest.mark.parametrize("domain", list(EXPECTED_RBAC.keys()))
def test_draft_rbac_matches_golden_blueprint(domain):
    """Re-derive RBAC for each known domain — must exactly match its committed blueprint.yaml."""
    fake_tools = [{"name": "x"}, {"name": "y"}, {"name": "z"}]
    result = draft_rbac(domain, fake_tools)

    assert result["scope"] == EXPECTED_SCOPE[domain]
    assert result["rbac"] == EXPECTED_RBAC[domain]
    assert all(scope == EXPECTED_SCOPE[domain] for scope in result["tool_scopes"].values())


def test_role_matrix_has_all_four_domains():
    assert set(ROLE_MATRIX.keys()) == set(EXPECTED_RBAC.keys())


def test_domain_scopes_has_all_four_domains():
    assert set(DOMAIN_SCOPES.keys()) == set(EXPECTED_SCOPE.keys())


@pytest.mark.parametrize("domain", list(EXPECTED_RBAC.keys()))
def test_fallback_tools_shape(domain):
    """suggest_tools' fallback (used when LLM is unavailable) must produce
    exactly 3 tools, each taking patient_id as the first parameter — same
    shape the real LLM-backed call is instructed to produce."""
    tools = _fallback_tools(domain, schema={})
    assert len(tools) == 3
    for tool in tools:
        assert "name" in tool and "signature" in tool
        assert tool["signature"].startswith("(patient_id: str")
