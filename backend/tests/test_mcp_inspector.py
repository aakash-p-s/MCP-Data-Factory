"""MCP Inspector-equivalent smoke — tools/list on all 4 servers (Jul 8).

In-process TestClient (no live ports required). Verifies each server exposes exactly 3 tools
with the frozen contract names when called with a physician token.
"""

from __future__ import annotations

import pytest

from backend.tests.rbac_fixtures import (
    MCP_HEADERS,
    SERVER_SPECS,
    TOOLS_LIST_BODY,
    bearer_token,
    mcp_test_client,
)


@pytest.mark.parametrize("server", list(SERVER_SPECS))
def test_inspector_tools_list_physician(server: str):
    """Physician token → tools/list → 200 and all blueprint tool names present."""
    expected = SERVER_SPECS[server]["tools"]
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {bearer_token('physician')}"}

    with mcp_test_client(server) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["service"] == server

        resp = client.post("/mcp", headers=headers, json=TOOLS_LIST_BODY)

    assert resp.status_code == 200, resp.text[:500]
    body = resp.text
    for tool in expected:
        assert tool in body, f"{tool} missing from tools/list on {server}"


@pytest.mark.parametrize("server", list(SERVER_SPECS))
def test_inspector_health_no_auth(server: str):
    """Health summary is public (no Bearer required)."""
    with mcp_test_client(server) as client:
        resp = client.get("/health")
    info = resp.json()
    assert info["fixed_core"] is True
    assert info["tools"] == SERVER_SPECS[server]["tools"]
