"""Unit tests for per-role usage / denial counters (Person A PRD §5.3)."""

from __future__ import annotations

import pytest

from backend.shared import usage_log


@pytest.fixture(autouse=True)
def _clean_counters():
    usage_log.reset()
    yield
    usage_log.reset()


def test_role_of_maps_groups():
    assert usage_log.role_of({"groups": ["grp-physician"]}) == "physician"
    assert usage_log.role_of({"groups": ["/grp-case-manager"]}) == "case-manager"
    assert usage_log.role_of({"groups": ["grp-unknown"]}) == "unknown"
    assert usage_log.role_of(None) == "anonymous"


def test_record_counts_allowed_and_denied():
    usage_log.record("physician", "vitals_trends", "allowed")
    usage_log.record("physician", "vitals_trends", "allowed")
    usage_log.record("physician", "vitals_trends", "denied")

    rows = usage_log.snapshot("vitals_trends")
    assert len(rows) == 1
    assert rows[0]["allowed"] == 2
    assert rows[0]["denied"] == 1
    assert rows[0]["role"] == "physician"


def test_snapshot_filters_by_server():
    usage_log.record("physician", "vitals_trends", "allowed")
    usage_log.record("physician", "labs_diagnoses", "allowed")
    assert len(usage_log.snapshot("vitals_trends")) == 1
    assert len(usage_log.snapshot()) == 2
