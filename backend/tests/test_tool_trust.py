"""Unit tests for the tool-trust / tool-poisoning guard (Person A PRD §5.3)."""

from __future__ import annotations

import pytest

from backend.shared import tool_trust


def test_kong_origin_allows_all_when_not_enforced(monkeypatch):
    monkeypatch.setattr(tool_trust, "ENFORCE", False)
    trusted, reason = tool_trust.verify_kong_origin({})
    assert trusted and reason is None


def test_kong_origin_denies_direct_call_when_enforced(monkeypatch):
    monkeypatch.setattr(tool_trust, "ENFORCE", True)
    monkeypatch.setattr(tool_trust, "KONG_TRUST_SECRET", "s3cret")
    trusted, reason = tool_trust.verify_kong_origin({"authorization": "Bearer x"})
    assert not trusted
    assert "Kong route" in reason


def test_kong_origin_allows_matching_secret(monkeypatch):
    monkeypatch.setattr(tool_trust, "ENFORCE", True)
    monkeypatch.setattr(tool_trust, "KONG_TRUST_SECRET", "s3cret")
    trusted, _ = tool_trust.verify_kong_origin({"x-kong-trust": "s3cret"})
    assert trusted


def test_kong_origin_allows_kong_proxy_marker(monkeypatch):
    monkeypatch.setattr(tool_trust, "ENFORCE", True)
    monkeypatch.setattr(tool_trust, "KONG_TRUST_SECRET", "")
    trusted, _ = tool_trust.verify_kong_origin({"x-kong-request-id": "abc-123"})
    assert trusted


def test_assert_registered_tools_passes_on_exact_match():
    tool_trust.assert_registered_tools(["a", "b"], ["b", "a"])  # order-independent


def test_assert_registered_tools_raises_on_injected_tool():
    with pytest.raises(RuntimeError, match="tool-trust violation"):
        tool_trust.assert_registered_tools(["a", "b", "evil"], ["a", "b"])
