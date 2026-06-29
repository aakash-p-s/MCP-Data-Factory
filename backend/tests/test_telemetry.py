"""Unit tests for telemetry trace-id propagation (Person A PRD §5.3)."""

from __future__ import annotations

import re

from backend.shared import telemetry

_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def test_extract_trace_id_parses_w3c_traceparent():
    tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    assert telemetry.extract_trace_id({"traceparent": tp}) == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_extract_trace_id_ignores_all_zero_traceparent():
    tp = "00-" + "0" * 32 + "-00f067aa0ba902b7-01"
    tid = telemetry.extract_trace_id({"traceparent": tp})
    assert _HEX32.match(tid) and tid != "0" * 32


def test_extract_trace_id_falls_back_to_x_trace_id():
    assert telemetry.extract_trace_id({"x-trace-id": "abc123"}) == "abc123"


def test_extract_trace_id_mints_when_absent():
    tid = telemetry.extract_trace_id({})
    assert _HEX32.match(tid)


def test_span_is_noop_without_configured_tracer():
    # No OTLP endpoint in the test env -> tracer is None -> span must not raise.
    with telemetry.span("test.op", trace_id="deadbeef", role="physician"):
        pass
