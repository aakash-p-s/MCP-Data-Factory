"""OpenTelemetry trace propagation — Codebase PRD §5.3 / Person A PRD §5.3.

Person B's runtime agent ORIGINATES one trace per clinical question (W3C `traceparent`
header); each Person A server CONTINUES that same trace so a single question is one
end-to-end trace across all four servers in Jaeger.

Two layers, both degrade gracefully:
  1. `extract_trace_id(headers)` — pure-Python W3C `traceparent` parse (zero deps). Always
     available, so the audit log's `trace_id` is the REAL 32-hex id, not the raw header.
     If the caller sends no trace, we mint one so every PHI record is still correlatable.
  2. `configure(service)` + `span(...)` — real OTel spans exported to the OTLP endpoint
     (Jaeger at :4317 in compose) WHEN the `opentelemetry` SDK is installed and
     `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Otherwise both are safe no-ops, so the servers
     run with or without the SDK and the test suite needs no heavy deps.
"""

from __future__ import annotations

import os
import secrets
from contextlib import contextmanager
from typing import Iterator

OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
TELEMETRY_ENABLED = os.getenv("TELEMETRY_ENABLED", "true").lower() in ("1", "true", "yes")

_tracer = None          # set by configure() when the OTel SDK is present
_configured = False


def extract_trace_id(headers: dict[str, str]) -> str:
    """Return the 32-hex W3C trace-id from request headers, minting one if absent.

    `traceparent` is `version-traceid-spanid-flags` (e.g.
    `00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01`); we want the 2nd field.
    Falls back to a bare `x-trace-id` header, then to a freshly generated id so the audit
    record is never null.
    """
    traceparent = headers.get("traceparent", "")
    if traceparent:
        parts = traceparent.split("-")
        if len(parts) >= 3 and len(parts[1]) == 32 and parts[1] != "0" * 32:
            return parts[1]
    explicit = headers.get("x-trace-id", "").strip()
    if explicit:
        return explicit
    return secrets.token_hex(16)   # 16 bytes -> 32 hex chars, W3C-shaped


def configure(service_name: str) -> None:
    """Set up an OTLP tracer once, if the OTel SDK + endpoint are available.

    No-op (and never raises) when the SDK isn't installed or no endpoint is configured —
    Person A's servers must run in either case.
    """
    global _tracer, _configured
    if _configured:
        return
    _configured = True
    if not (TELEMETRY_ENABLED and OTLP_ENDPOINT):
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return   # SDK not installed — trace_id propagation still works via extract_trace_id

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP_ENDPOINT)))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(service_name)


@contextmanager
def span(name: str, trace_id: str | None = None, **attributes) -> Iterator[None]:
    """Open a span for the current operation. No-op when OTel isn't configured."""
    if _tracer is None:
        yield
        return
    with _tracer.start_as_current_span(name) as sp:
        if trace_id:
            sp.set_attribute("app.trace_id", trace_id)
        for key, value in attributes.items():
            if value is not None:
                sp.set_attribute(key, value)
        yield
