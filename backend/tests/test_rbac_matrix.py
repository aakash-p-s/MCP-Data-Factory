"""Unit tests for the Fixed Core auth engine (Layer-2 RBAC matrix)."""

from __future__ import annotations

import jwt
import pytest

from backend.shared.auth import check_groups, check_scope, evaluate, groups_of, scopes_of

_SECRET = "x" * 32


def _token(scp: str = "", groups: list[str] | None = None) -> dict:
    return jwt.decode(
        jwt.encode({"scp": scp, "groups": groups or []}, _SECRET, algorithm="HS256"),
        options={"verify_signature": False},
    )


# --- scope checks -----------------------------------------------------------
def test_scope_present():
    claims = _token("mcp.vitals.read mcp.labs.read")
    assert check_scope(claims, "mcp.vitals.read")
    assert not check_scope(claims, "mcp.meds.read")


# --- group checks (blueprint matrix) ----------------------------------------
def test_groups_normalises_keycloak_paths():
    assert groups_of({"groups": ["/grp-physician", "grp-clinical-viewer"]}) == {
        "grp-physician", "grp-clinical-viewer",
    }


def test_groupless_service_account_allowed():
    """Runtime agent token with no groups still passes (POC service account)."""
    claims = _token("mcp.vitals.read", groups=[])
    assert check_groups(claims, {"grp-clinical-viewer", "grp-physician"})


def test_case_manager_denied_vitals():
    claims = _token("mcp.vitals.read mcp.labs.read", groups=["grp-case-manager"])
    ok, reason = evaluate(claims, "mcp.vitals.read", {"grp-clinical-viewer", "grp-physician"}, "vitals_trends")
    assert not ok
    assert "role not permitted" in reason


def test_nurse_allowed_vitals_and_labs():
    claims = _token("mcp.vitals.read mcp.labs.read", groups=["grp-clinical-viewer"])
    assert evaluate(claims, "mcp.vitals.read", {"grp-clinical-viewer", "grp-physician"})[0]
    assert evaluate(claims, "mcp.labs.read", {"grp-clinical-viewer", "grp-physician"})[0]


def test_nurse_denied_meds():
    claims = _token("mcp.meds.read", groups=["grp-clinical-viewer"])
    ok, _ = evaluate(claims, "mcp.meds.read", {"grp-physician"}, "medications_interactions")
    assert not ok


def test_physician_allowed_all_sql_scopes():
    groups = ["grp-physician"]
    claims_v = _token("mcp.vitals.read", groups)
    claims_l = _token("mcp.labs.read", groups)
    claims_m = _token("mcp.meds.read", groups)
    assert evaluate(claims_v, "mcp.vitals.read", {"grp-clinical-viewer", "grp-physician"})[0]
    assert evaluate(claims_l, "mcp.labs.read", {"grp-clinical-viewer", "grp-physician"})[0]
    assert evaluate(claims_m, "mcp.meds.read", {"grp-physician"})[0]


def test_missing_scope_denied_before_group_check():
    claims = _token("", groups=["grp-physician"])
    ok, reason = evaluate(claims, "mcp.vitals.read", {"grp-physician"})
    assert not ok
    assert reason == "missing scope mcp.vitals.read"


def test_case_manager_allowed_notes():
    claims = _token("mcp.notes.read", groups=["grp-case-manager"])
    assert evaluate(claims, "mcp.notes.read", {"grp-physician", "grp-case-manager"})[0]


def test_nurse_denied_notes():
    claims = _token("mcp.notes.read", groups=["grp-clinical-viewer"])
    ok, _ = evaluate(claims, "mcp.notes.read", {"grp-physician", "grp-case-manager"}, "clinical_notes_search")
    assert not ok
