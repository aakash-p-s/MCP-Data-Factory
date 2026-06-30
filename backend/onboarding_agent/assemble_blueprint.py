"""
backend/onboarding_agent/assemble_blueprint.py

Stage 4 of 4 - Blueprint assembly (Codebase PRD section 5.5 / ONBOARDING_AGENT.md).

Writes blueprint.yaml - the agent's ONLY output, and the human-approval
artifact. This function never deploys anything, never touches Kong, the
registry, or any database beyond the read-only schema() call already made
in discover.py. A human reviews the written YAML; only then does the
existing hardened template (Person A's backend/servers/*) generate the
server.

Output shape MUST match the 4 committed blueprints exactly (golden-file
fixtures) for the 4 known domains - see backend/servers/<domain>/blueprint.yaml.
For a new domain, storage/fhir_resource/terminology come from the LLM
inference in suggest_tools.suggest_tools_and_metadata() (passed in via the
`inferred_metadata` parameter) rather than the static _DOMAIN_META lookup.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Per-domain metadata the blueprint needs beyond what discover/suggest/rbac
# produce - storage backend, FHIR resource, terminology, Kong route. Mirrors
# HANDOVER_PERSON_B.md section 7's registry seed table exactly. ONLY covers
# the 4 frozen domains - any other domain falls through to LLM-inferred
# metadata (see inferred_metadata param) or "unknown" if neither is available.
_DOMAIN_META: dict[str, dict[str, str]] = {
    "vitals_trends": {
        "storage": "timescaledb",
        "fhir_resource": "Observation",
        "terminology": "LOINC",
        "kong_route": "/mcp/clinical/vitals-trends/dev",
    },
    "labs_diagnoses": {
        "storage": "postgres",
        "fhir_resource": "Observation, Condition",
        "terminology": "LOINC, SNOMED-CT, ICD-10",
        "kong_route": "/mcp/clinical/labs-diagnoses/dev",
    },
    "medications_interactions": {
        "storage": "postgres",
        "fhir_resource": "MedicationStatement",
        "terminology": "RxNorm",
        "kong_route": "/mcp/clinical/medications-interactions/dev",
    },
    "clinical_notes_search": {
        "storage": "qdrant",
        "fhir_resource": "DocumentReference",
        "terminology": None,  # free text, embedded - no fixed terminology
        "kong_route": "/mcp/clinical/clinical-notes-search/dev",
    },
}


def _resolve_domain_meta(domain: str, inferred_metadata: dict | None) -> dict:
    """
    Resolution order for storage / fhir_resource / terminology / kong_route:
      1. The frozen _DOMAIN_META table (only the 4 known domains)
      2. LLM-inferred metadata from suggest_tools_and_metadata(), if provided
      3. "unknown" placeholders, as a last resort the human approver must fill in
    """
    if domain in _DOMAIN_META:
        return _DOMAIN_META[domain]

    kong_route = f"/mcp/clinical/{domain.replace('_', '-')}/dev"

    if inferred_metadata:
        return {
            "storage": inferred_metadata.get("storage") or "unknown",
            "fhir_resource": inferred_metadata.get("fhir_resource") or "unknown",
            "terminology": inferred_metadata.get("terminology"),
            "kong_route": kong_route,
        }

    logger.warning(
        "assemble_blueprint: no metadata (static or inferred) for domain %r - "
        "writing 'unknown' placeholders; human approver must fill these in.",
        domain,
    )
    return {
        "storage": "unknown",
        "fhir_resource": "unknown",
        "terminology": None,
        "kong_route": kong_route,
    }


def assemble_blueprint(
    domain: str,
    schema: dict,
    tools: list[dict],
    rbac: dict,
    output_dir: str | Path = "backend/onboarding_agent/output",
    inferred_metadata: dict | None = None,
) -> Path:
    """
    Input:  domain, schema (from discover.py), tools (from suggest_tools.py),
            rbac (from draft_rbac.py - has "scope" and "rbac" keys),
            inferred_metadata (optional) - {"storage", "fhir_resource",
            "terminology"} from suggest_tools.suggest_tools_and_metadata(),
            used only when domain is not one of the 4 frozen domains.
    Output: Path to the written blueprint.yaml

    The human approver reads this file directly (Person B PRD section 5.4:
    "Human Approver reviews the blueprint file directly - no UI required").
    """
    meta = _resolve_domain_meta(domain, inferred_metadata)

    denial_envelope = (
        '{"error":{"code":"forbidden","reason":"missing scope ' + rbac["scope"] + '"}}'
    )

    blueprint: dict = {
        "domain": domain,
        "storage": meta["storage"],
        "fhir_resource": meta["fhir_resource"],
        "scope": rbac["scope"],
        "kong_route": meta["kong_route"],
        "mcp_endpoint": "/mcp",
        "status": "draft",  # becomes "DB-backed" only after human approval + build
        "tools": [
            {
                "name": tool["name"],
                "signature": tool["signature"],
            }
            for tool in tools
        ],
        "rbac": rbac["rbac"],
        "denial_envelope": denial_envelope,
    }
    if meta.get("terminology"):
        blueprint["terminology"] = meta["terminology"]

    # PRD: "discovered FHIR-shaped schema" is kept alongside the blueprint as
    # an audit trail of what discover.py actually saw - not part of the
    # frozen contract itself, but useful for the human approver's review.
    discovery_record = {
        "discovered_schema": schema,
        "suggested_tool_descriptions": {
            t["name"]: t.get("description", "") for t in tools
        },
        "metadata_source": "frozen_table" if domain in _DOMAIN_META else (
            "llm_inferred" if inferred_metadata else "unknown_placeholder"
        ),
    }

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    blueprint_path = out_dir / f"{domain}.blueprint.yaml"
    discovery_path = out_dir / f"{domain}.discovery.yaml"

    with open(blueprint_path, "w") as f:
        yaml.safe_dump(blueprint, f, sort_keys=False, default_flow_style=False)

    with open(discovery_path, "w") as f:
        yaml.safe_dump(discovery_record, f, sort_keys=False, default_flow_style=False)

    logger.info("assemble_blueprint: wrote %s (+ discovery record)", blueprint_path)

    return blueprint_path
