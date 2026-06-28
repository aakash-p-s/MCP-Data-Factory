"""HTTP-level RBAC matrix — 4 servers × 3 roles (Jul 3 / Jul 8 acceptance)."""

from __future__ import annotations

import pytest

from backend.tests.rbac_fixtures import (
    MCP_HEADERS,
    TOOLS_LIST_BODY,
    bearer_token,
    matrix_cases,
    mcp_test_client,
)


@pytest.mark.parametrize("role,server,expect_allow", list(matrix_cases()))
def test_rbac_matrix_tools_list(role: str, server: str, expect_allow: bool):
    """FixedCoreGuard must allow/deny tools/list per blueprint RBAC matrix."""
    token = bearer_token(role)
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {token}"}

    with mcp_test_client(server) as client:
        resp = client.post("/mcp", headers=headers, json=TOOLS_LIST_BODY)

    if expect_allow:
        assert resp.status_code == 200, resp.text[:500]
    else:
        assert resp.status_code == 403
        body = resp.json()
        assert body["error"]["code"] == "forbidden"
        assert "reason" in body["error"]


def test_no_bearer_token_returns_401():
    with mcp_test_client("vitals_trends") as client:
        resp = client.post("/mcp", headers=MCP_HEADERS, json=TOOLS_LIST_BODY)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("role,server,expect_allow", list(matrix_cases()))
def test_rbac_matrix_auth_engine_matches_http(role: str, server: str, expect_allow: bool):
    """auth.evaluate() agrees with the HTTP matrix (sanity cross-check)."""
    import jwt

    from backend.shared.auth import evaluate
    from backend.tests.rbac_fixtures import SERVER_SPECS, _SECRET

    token = bearer_token(role)
    claims = jwt.decode(token, options={"verify_signature": False})
    spec = SERVER_SPECS[server]
    ok, _ = evaluate(claims, spec["scope"], spec["allowed_groups"], server)
    assert ok == expect_allow
