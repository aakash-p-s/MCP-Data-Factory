"""Unit tests for VectorConnector and clinical_notes_search tools."""

from __future__ import annotations

import asyncio

import jwt
import pytest

from backend.connectors.vector_connector import VectorConnector
from backend.servers.clinical_notes_search import tools
from backend.shared.auth import evaluate
from backend.shared.egress_guard import locked_connector_for


def test_document_reference_shape():
    doc = tools._document_reference({
        "id": 42,
        "patient_id": "p-1",
        "note_type": "physician_note",
        "note_date": "2020-01-15",
        "author": "physician",
        "text": "Patient reports dizziness.",
    })
    assert doc["resourceType"] == "DocumentReference"
    assert doc["id"] == "42"
    assert doc["subject"]["reference"] == "Patient/p-1"
    assert doc["type"]["text"] == "physician_note"
    assert doc["text"] == "Patient reports dizziness."


def test_vector_query_rejects_unknown_mode():
    conn = VectorConnector("http://localhost:6333")
    conn._client = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock()
    conn._verified = True
    with pytest.raises(ValueError, match="unsupported vector query mode"):
        asyncio.run(conn.query({"mode": "drop_table", "patient_id": "p1"}))


def test_vector_by_type_requires_note_type():
    conn = VectorConnector("http://localhost:6333")
    conn._client = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock()
    conn._verified = True
    with pytest.raises(ValueError, match="note_type is required"):
        asyncio.run(conn.query({"mode": "by_type", "patient_id": "p1"}))


def test_semantic_search_empty_query_returns_empty():
    conn = VectorConnector("http://localhost:6333")
    conn._client = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock()
    conn._verified = True

    async def run():
        return await tools.semantic_search_notes(conn, "p1", "   ")

    assert asyncio.run(run()) == []


def test_semantic_search_uses_query_points(monkeypatch):
    """Search must use the current qdrant-client query_points() API (not removed .search())."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    conn = VectorConnector("http://localhost:6333")
    client = AsyncMock()
    point = SimpleNamespace(
        id=7, score=0.91,
        payload={"patient_id": "p1", "note_type": "physician_note", "text": "chest pain noted"})
    client.query_points = AsyncMock(return_value=SimpleNamespace(points=[point]))
    conn._client = client
    conn._verified = True
    monkeypatch.setattr("backend.connectors.vector_connector.embed", lambda _t: [0.0] * 384)

    async def run():
        return await conn.query(
            {"mode": "search", "patient_id": "p1", "query_text": "chest pain", "limit": 3})

    rows = asyncio.run(run())
    assert client.query_points.await_count == 1
    assert len(rows) == 1 and rows[0]["id"] == 7 and rows[0]["score"] == 0.91


def test_egress_guard_registers_notes_server():
    conn = locked_connector_for("clinical_notes_search")
    assert type(conn).__name__ == "VectorConnector"


def test_rbac_notes_case_manager_allowed():
    claims = jwt.decode(
        jwt.encode({"scp": "mcp.notes.read", "groups": ["grp-case-manager"]}, "x" * 32, algorithm="HS256"),
        options={"verify_signature": False},
    )
    ok, _ = evaluate(claims, "mcp.notes.read", {"grp-physician", "grp-case-manager"}, "clinical_notes_search")
    assert ok


def test_rbac_notes_nurse_denied():
    claims = jwt.decode(
        jwt.encode({"scp": "mcp.notes.read", "groups": ["grp-clinical-viewer"]}, "x" * 32, algorithm="HS256"),
        options={"verify_signature": False},
    )
    ok, reason = evaluate(claims, "mcp.notes.read", {"grp-physician", "grp-case-manager"}, "clinical_notes_search")
    assert not ok
    assert "role not permitted" in reason
