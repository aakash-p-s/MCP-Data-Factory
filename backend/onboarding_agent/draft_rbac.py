"""
backend/onboarding_agent/draft_rbac.py

Stage 3 of 4 - RBAC drafting (Codebase PRD section 6.3 / ONBOARDING_AGENT.md).

Applies the FIXED role matrix to a tool list, producing per-tool scopes.
This is deterministic, not LLM-based, for the 4 KNOWN domains - RBAC is the
one thing the PRD does not want left to LLM judgement.

For a genuinely NEW domain (not one of the existing 4), draft_rbac proposes
a conservative default and allows manual override via the approval CLI's
"Modify RBAC" path - this is where "Limited" access tiers (e.g. read-only
summary but not full detail) get encoded as a per-tool override rather
than a per-server allow/deny, since the frozen matrix is server-level only.

Matrix (Codebase PRD section 6.3) for the 4 existing domains:

    Role              vitals  labs  meds  notes
    clinical-viewer    allow  allow deny  deny
    physician          allow  allow allow allow
    case-manager       deny   deny  deny  allow
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Frozen RBAC matrix - PRD section 6.3. Do not infer this from the LLM for
# the 4 existing domains; it is fixed.
ROLE_MATRIX: dict[str, dict[str, str]] = {
    "vitals_trends": {
        "clinical-viewer": "allow",
        "physician": "allow",
        "case-manager": "deny",
    },
    "labs_diagnoses": {
        "clinical-viewer": "allow",
        "physician": "allow",
        "case-manager": "deny",
    },
    "medications_interactions": {
        "clinical-viewer": "deny",
        "physician": "allow",
        "case-manager": "deny",
    },
    "clinical_notes_search": {
        "clinical-viewer": "deny",
        "physician": "allow",
        "case-manager": "allow",
    },
}

# Per-domain scope string - matches blueprint.yaml `scope:` field exactly
DOMAIN_SCOPES: dict[str, str] = {
    "vitals_trends": "mcp.vitals.read",
    "labs_diagnoses": "mcp.labs.read",
    "medications_interactions": "mcp.meds.read",
    "clinical_notes_search": "mcp.notes.read",
}

# Valid per-role access levels - "allow"/"deny" are the only values the
# frozen matrix uses for the 4 existing domains. "limited" is available for
# NEW domains going through the approval CLI's "Modify RBAC" path, meaning
# the role can call summary/read tools but not detail tools - encoded at
# assemble_blueprint time as a per-tool allow-list rather than a single
# server-level scope grant.
VALID_ACCESS_LEVELS = ("allow", "deny", "limited")


def draft_rbac(domain: str, tools: list[dict], role_matrix: dict | None = None) -> dict:
    """
    Input:  domain name, list of suggested tools (from suggest_tools.py),
            optional role_matrix override (defaults to the frozen PRD matrix
            for the 4 known domains; required for a genuinely new domain).
    Output: {
              "scope": "mcp.<domain_short>.read",
              "rbac": {"clinical-viewer": "allow"|"deny"|"limited", ...},
              "tool_scopes": {tool_name: scope, ...}
            }
    """
    matrix = role_matrix or ROLE_MATRIX

    # scope lookup is INTENTIONALLY separate from the rbac-matrix lookup
    # below: a caller may pass a custom role_matrix (e.g. main.py rebuilding
    # tool_scopes after "Modify Tools" regenerates tool names) that only
    # carries rbac allow/deny values, not a real DOMAIN_SCOPES entry - that
    # must never raise KeyError for a domain outside the frozen 4.
    scope = DOMAIN_SCOPES.get(domain) or f"mcp.{domain.split('_')[0]}.read"

    if domain in matrix:
        rbac = dict(matrix[domain])
    else:
        # New domain not in the frozen 4 - conservative default proposal,
        # shown to the human via the approval CLI's "Modify RBAC" option.
        logger.warning(
            "draft_rbac: domain %r not in frozen matrix - proposing conservative default",
            domain,
        )
        rbac = {"clinical-viewer": "limited", "physician": "allow", "case-manager": "deny"}

    tool_scopes = {tool["name"]: scope for tool in tools}

    logger.info("draft_rbac: %s -> scope=%s rbac=%s", domain, scope, rbac)

    return {
        "scope": scope,
        "rbac": rbac,
        "tool_scopes": tool_scopes,
    }


def apply_rbac_override(rbac: dict, role: str, new_level: str) -> dict:
    """
    Apply a human reviewer's manual RBAC edit (approval CLI option 2 -
    "Modify RBAC"). Returns a NEW rbac dict; never mutates in place, so the
    caller can keep the original proposal for the discovery.yaml audit trail.
    """
    if new_level not in VALID_ACCESS_LEVELS:
        raise ValueError(
            f"invalid access level {new_level!r}; must be one of {VALID_ACCESS_LEVELS}"
        )
    updated = dict(rbac)
    updated["rbac"] = dict(rbac["rbac"])
    updated["rbac"][role] = new_level
    logger.info("apply_rbac_override: %s -> %s", role, new_level)
    return updated
