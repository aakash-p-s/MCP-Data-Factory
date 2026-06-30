"""Runtime agent helper tests — purpose normalization and static discovery."""

from __future__ import annotations

import pytest

from agent.runtime_agent import (
    _STATIC_RBAC,
    _STATIC_URLS,
    normalize_purpose,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("medication_review", "medication_reconciliation"),
        ("meds_review", "medication_reconciliation"),
        ("routine_review", "routine_review"),
    ],
)
def test_normalize_purpose_aliases(raw, expected):
    assert normalize_purpose(raw) == expected


def test_static_discovery_includes_radiology():
    assert "radiology_reports" in _STATIC_URLS
    assert "radiology_reports" in _STATIC_RBAC
    assert _STATIC_URLS["radiology_reports"].endswith(":8005/mcp")
