"""Usage / cost log — Person A PRD §5.3.

In-process counters of query count + denial count, broken down by role, server, and ISO
week. Read-only analytics fed by FixedCoreGuard on every auth decision; surfaced at each
server's `/usage` endpoint so the dashboard / anomaly panel can group meaningfully without
new infrastructure (registry-db persistence is out of Person A's sprint scope).
"""

from __future__ import annotations

import datetime
import threading
from collections import defaultdict

# (role, server, iso_week) -> {"allowed": int, "denied": int}
_counts: dict[tuple[str, str, str], dict[str, int]] = defaultdict(
    lambda: {"allowed": 0, "denied": 0})
_lock = threading.Lock()

_GROUP_TO_ROLE = {
    "grp-clinical-viewer": "clinical-viewer",
    "grp-physician": "physician",
    "grp-case-manager": "case-manager",
}


def role_of(claims: dict | None) -> str:
    """Map a token's groups to a single role label for usage grouping."""
    if not claims:
        return "anonymous"
    for group in claims.get("groups") or []:
        role = _GROUP_TO_ROLE.get(group.lstrip("/"))
        if role:
            return role
    return "unknown"


def _iso_week(now: datetime.datetime | None = None) -> str:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def record(role: str, server: str, outcome: str) -> None:
    """Count one decision. `outcome` is 'allowed' or 'denied'."""
    bucket = "allowed" if outcome == "allowed" else "denied"
    with _lock:
        _counts[(role, server, _iso_week())][bucket] += 1


def snapshot(server: str | None = None) -> list[dict]:
    """Return the current counters, optionally filtered to one server."""
    with _lock:
        rows = [
            {"role": role, "server": srv, "week": week,
             "allowed": c["allowed"], "denied": c["denied"]}
            for (role, srv, week), c in _counts.items()
            if server is None or srv == server
        ]
    rows.sort(key=lambda r: (r["week"], r["server"], r["role"]))
    return rows


def reset() -> None:
    """Clear all counters (used by tests)."""
    with _lock:
        _counts.clear()
