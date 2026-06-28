"""Unit tests for audit, cache, and egress guard."""

from __future__ import annotations

import asyncio
import time

import pytest

from backend.shared.audit import DEFAULT_PURPOSE, PURPOSE_OF_ACCESS, audit_phi, log_call, normalize_purpose
from backend.shared.cache import cached
from backend.shared.egress_guard import locked_connector_for
from backend.shared.request_context import clear_context, set_context


def test_purpose_enum_rejects_invalid():
    with pytest.raises(ValueError, match="invalid purpose_of_access"):
        log_call("u", "what", "allowed", purpose_of_access="not_a_real_purpose")


def test_purpose_enum_accepts_all_values():
    for p in PURPOSE_OF_ACCESS:
        rec = log_call("u", "what", "allowed", purpose_of_access=p)
        assert rec["purpose_of_access"] == p


def test_normalize_purpose_defaults():
    assert normalize_purpose(None) == DEFAULT_PURPOSE
    assert normalize_purpose("deterioration_review") == "deterioration_review"
    assert normalize_purpose("bogus") == DEFAULT_PURPOSE


def test_audit_phi_uses_request_context(capsys):
    set_context({"sub": "nurse-1"}, "care_coordination", "trace-abc")
    try:
        audit_phi("get_vitals_trend", "patient-123")
    finally:
        clear_context()
    out = capsys.readouterr().out
    assert "AUDIT" in out
    assert "nurse-1" in out
    assert "get_vitals_trend:patient-123" in out
    assert "care_coordination" in out


def test_cache_serves_second_call_within_ttl():
    calls = 0

    @cached(ttl_seconds=30)
    async def expensive(_conn, patient_id: str) -> str:
        nonlocal calls
        calls += 1
        return f"{patient_id}-{calls}"

    async def run():
        assert await expensive(None, "p1") == "p1-1"
        assert await expensive(None, "p1") == "p1-1"
        assert calls == 1

    asyncio.run(run())


def test_egress_guard_registers_all_backends():
    for name in ("vitals_trends", "labs_diagnoses", "medications_interactions"):
        conn = locked_connector_for(name)
        assert conn._dsn  # noqa: SLF001 — DSN bound at construction
    notes = locked_connector_for("clinical_notes_search")
    assert type(notes).__name__ == "VectorConnector"


def test_egress_guard_rejects_unknown_server():
    with pytest.raises(KeyError, match="no egress-allowed backend"):
        locked_connector_for("unknown_server")
