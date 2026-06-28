"""Audit log — Codebase PRD §5.2 / §6.4.

Every call (allowed or denied) produces one structured record. purpose_of_access is a
FIXED enum (gap fix) — validated, not free text — so audit analytics / the anomaly panel
can group meaningfully. Writes to stdout (registry-db is out of Person A's sprint scope).
"""

from __future__ import annotations

import datetime
import json
import sys

# fixed enum — routine_review is the default (§6.4)
PURPOSE_OF_ACCESS = {
    "deterioration_review",
    "medication_reconciliation",
    "discharge_planning",
    "care_coordination",
    "routine_review",
}
DEFAULT_PURPOSE = "routine_review"


def normalize_purpose(value: str | None) -> str:
    """Return a valid enum value, falling back to the default for empty input."""
    return value if value in PURPOSE_OF_ACCESS else DEFAULT_PURPOSE


def audit_phi(tool_name: str, patient_id: str, outcome: str = "allowed",
              reason: str | None = None) -> dict:
    """Audit one PHI-touching tool call (uses request context set by FixedCoreGuard)."""
    from backend.shared.request_context import get_context

    ctx = get_context()
    purpose = ctx.purpose_of_access if ctx else DEFAULT_PURPOSE
    trace_id = ctx.trace_id if ctx else None
    who = str(ctx.claims.get("sub") or "anonymous") if ctx and ctx.claims else "anonymous"
    return log_call(who, f"{tool_name}:{patient_id}", outcome, reason, purpose, trace_id)


def log_call(who: str, what: str, outcome: str, reason: str | None = None,
             purpose_of_access: str = DEFAULT_PURPOSE, trace_id: str | None = None) -> dict:
    """Write one audit record. Raises ValueError on an invalid purpose_of_access."""
    if purpose_of_access not in PURPOSE_OF_ACCESS:
        raise ValueError(f"invalid purpose_of_access: {purpose_of_access!r}")
    record = {
        "who": who,
        "what": what,
        "when": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "outcome": outcome,
        "reason": reason,
        "purpose_of_access": purpose_of_access,
        "trace_id": trace_id,
    }
    print("AUDIT " + json.dumps(record), file=sys.stdout, flush=True)
    return record
