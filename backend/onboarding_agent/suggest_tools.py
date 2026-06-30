"""
backend/onboarding_agent/suggest_tools.py

Stage 2 of 4 - Tool suggestion (Codebase PRD section 5.5 / ONBOARDING_AGENT.md).

One LLM call: schema -> draft {name, description, signature} tool triples,
PLUS inferred metadata (storage type, FHIR resource) for domains not in the
frozen 4 (Codebase PRD section 6.2's table only covers the existing domains -
assemble_blueprint.py's _DOMAIN_META lookup falls back to "unknown" for any
new domain, so the LLM is asked to propose a value instead, which the human
approver can override exactly like tools/RBAC).

Follows the same retry-with-fallback pattern as the platform's other LLM
call (agent/runtime_agent.py's synthesis step) - malformed JSON is retried
up to 3 times total, then falls back to a deterministic stub so the pipeline
never blocks on a flaky LLM response.

Supports revision-on-reject (Codebase PRD Phase 1 diagram: "Reject -> revise
(back to 2)") via the optional feedback / previous_tools parameters.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Closed vocabularies the LLM must pick from - keeps inferred metadata
# consistent with what the rest of the platform (Kong routes, connectors,
# FHIR shaping in backend/shared) actually understands. Never let the LLM
# invent a storage type or FHIR resource outside these lists.
VALID_STORAGE_TYPES = ("postgres", "timescaledb", "qdrant")
VALID_FHIR_RESOURCES = (
    "Observation",
    "Condition",
    "MedicationStatement",
    "DocumentReference",
    "DiagnosticReport",
    "Procedure",
)

PROMPT_TEMPLATE = """You are designing a read-only MCP (Model Context Protocol) tool set for a
clinical data domain, for the Patient Risk Intelligence platform.

Given the discovered schema below for domain "{domain}", output ONLY a JSON object
with this exact shape:

NOTE: the schema includes a "fhir_shape" section with HEURISTIC, non-authoritative
guesses about FHIR field mappings and likely resource type (produced by simple
substring matching in discover.py, not by you). Treat these as hints to confirm,
correct, or override based on your own reasoning over the raw schema - do not
just copy them blindly.

{{
  "storage": "postgres" | "timescaledb" | "qdrant",
  "fhir_resource": "Observation" | "Condition" | "MedicationStatement" |
                    "DocumentReference" | "DiagnosticReport" | "Procedure",
  "terminology": "LOINC" | "RxNorm" | "SNOMED-CT" | "ICD-10" | null,
  "tools": [
    {{
      "name": "snake_case_tool_name",
      "description": "one sentence, what the tool returns",
      "signature": "(patient_id: str, ...) -> list[ResourceType] | dict"
    }}
  ]
}}

Rules for storage / fhir_resource / terminology:
- "storage": infer from the schema shape. If the schema has "vector_size" and
  "payload_fields" keys, it is a vector store -> "qdrant". If it has time-series-like
  columns (a timestamp column plus repeated readings), prefer "timescaledb". Otherwise
  "postgres".
- "fhir_resource": pick whichever FHIR resource type best matches what the table
  actually stores (e.g. a vitals/labs-shaped table -> Observation; a diagnosis/condition
  table -> Condition; a medication table -> MedicationStatement; free-text notes ->
  DocumentReference; imaging/lab report findings -> DiagnosticReport).
- "terminology": set this if there's an obvious standard coding system for the
  domain (Example:LOINC for labs/vitals, RxNorm for medications, SNOMED-CT/ICD-10 for
  diagnoses). Use null if no standard terminology applies (e.g. free-text notes).

Rules for tools:
- Suggest exactly 3 tools (matches the 4 existing domains' pattern: ~3 tools each).
- Every tool MUST take patient_id: str as its first parameter - this is a per-patient
  clinical platform, there is no cross-patient query surface.
- Tools must be read-only (the connector layer rejects any write/DDL query anyway).
- Prefer one "trend/history" tool, one "current state" tool, and one "summary/score"
  or "search" tool, mirroring the existing domains (e.g. vitals_trends has
  get_vitals_trend, compute_news2_score, list_abnormal_vitals).
- No preamble. No markdown fences. Pure JSON only.
{feedback_block}
Discovered schema:
{schema_json}
"""

FEEDBACK_BLOCK_TEMPLATE = """
IMPORTANT - this is a REVISION. The human reviewer rejected the previous proposal
with this feedback, which you MUST address:

  "{feedback}"

Previous tools that were rejected (do not just repeat these):
{previous_tools}
"""


def suggest_tools(
    domain: str,
    schema: dict,
    feedback: str | None = None,
    previous_tools: list[dict] | None = None,
) -> list[dict]:
    """
    Input:  domain name + the dict returned by discover.discover_schema()
            feedback (optional) - human reviewer's rejection reason, from a
                                   prior approval cycle
            previous_tools (optional) - what was rejected, so the LLM doesn't
                                         just repeat itself
    Output: list[{name, description, signature}]

    NOTE: storage/fhir_resource/terminology are inferred in the SAME LLM call
    but returned via suggest_metadata() below, not here, to keep this
    function's return type unchanged for existing callers (run.py, the
    golden-file tests). Call suggest_metadata() separately if you need those
    fields - it reuses the cached response from the same prompt/response
    cycle when called together via suggest_tools_and_metadata().
    """
    tools, _ = suggest_tools_and_metadata(domain, schema, feedback, previous_tools)
    return tools


def suggest_tools_and_metadata(
    domain: str,
    schema: dict,
    feedback: str | None = None,
    previous_tools: list[dict] | None = None,
) -> tuple[list[dict], dict]:
    """
    Single LLM call returning BOTH the tool list AND inferred metadata
    (storage, fhir_resource, terminology) for domains assemble_blueprint.py's
    _DOMAIN_META has no entry for.

    Returns: (tools, metadata) where metadata = {
        "storage": str, "fhir_resource": str, "terminology": str | None
    }
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        logger.warning("LLM unavailable (%s) - using fallback tool suggestions", exc)
        return _fallback_tools(domain, schema), _fallback_metadata(schema)

    feedback_block = ""
    if feedback:
        prev_str = json.dumps(previous_tools or [], indent=2)
        feedback_block = FEEDBACK_BLOCK_TEMPLATE.format(
            feedback=feedback, previous_tools=prev_str
        )

    prompt = PROMPT_TEMPLATE.format(
        domain=domain,
        feedback_block=feedback_block,
        schema_json=json.dumps(schema, indent=2, default=str)[:4000],
    )

    llm = ChatOpenAI(model="gpt-4o", temperature=0, openai_api_key=OPENAI_API_KEY)

    tools = None
    metadata = None
    for attempt in range(3):
        try:
            response = llm.invoke(prompt)
            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            parsed = json.loads(content)

            candidate_tools = parsed.get("tools", [])
            candidate_storage = parsed.get("storage")
            candidate_fhir = parsed.get("fhir_resource")
            candidate_terminology = parsed.get("terminology")

            # Validate against closed vocabularies - never trust the LLM to
            # stay in-bounds without checking.
            if candidate_storage not in VALID_STORAGE_TYPES:
                candidate_storage = None
            if candidate_fhir not in VALID_FHIR_RESOURCES:
                candidate_fhir = None

            if candidate_tools:
                tools = candidate_tools
                metadata = {
                    "storage": candidate_storage,
                    "fhir_resource": candidate_fhir,
                    "terminology": candidate_terminology,
                }
                break
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("suggest_tools attempt %d failed: %s", attempt + 1, exc)
            if attempt == 2:
                tools = _fallback_tools(domain, schema)
                metadata = _fallback_metadata(schema)

    logger.info(
        "suggest_tools: %d tools, storage=%s fhir_resource=%s for %s",
        len(tools or []),
        (metadata or {}).get("storage"),
        (metadata or {}).get("fhir_resource"),
        domain,
    )
    return tools or _fallback_tools(domain, schema), metadata or _fallback_metadata(schema)


def _fallback_tools(domain: str, schema: dict) -> list[dict]:
    """
    Deterministic fallback if the LLM is unavailable or never returns valid
    JSON - guarantees assemble_blueprint.py always has something to write,
    matching the golden-file pattern (3 tools per domain).
    """
    short = domain.replace("_search", "").replace("_trends", "")
    return [
        {
            "name": f"get_{short}_trend",
            "description": f"Recent {short} records for a patient.",
            "signature": "(patient_id: str, hours: int = 24) -> list[dict]",
        },
        {
            "name": f"get_active_{short}",
            "description": f"Current/active {short} state for a patient.",
            "signature": "(patient_id: str) -> dict",
        },
        {
            "name": f"list_abnormal_{short}",
            "description": f"{short} entries outside the normal/expected range.",
            "signature": "(patient_id: str, hours: int = 24) -> list[dict]",
        },
    ]


def _fallback_metadata(schema: dict) -> dict:
    """
    Deterministic fallback for storage/fhir_resource when the LLM is
    unavailable - cheap heuristics on the schema shape, same logic the
    prompt asks the LLM to apply.

    schema is the {"raw": ..., "fhir_shape": ...} dict from discover.py
    (or a flat raw dict, for backward compatibility with direct callers
    that bypass discover.py and pass raw schema straight in).
    """
    raw = schema.get("raw", schema) if isinstance(schema, dict) else schema
    fhir_shape = schema.get("fhir_shape", {}) if isinstance(schema, dict) else {}

    storage = "postgres"
    if isinstance(raw, dict) and ("vector_size" in raw or "payload_fields" in raw):
        storage = "qdrant"

    # Prefer discover.py's heuristic resource-type guess if it found one
    fhir_resource = "Observation"
    if isinstance(fhir_shape, dict):
        for entry in fhir_shape.values():
            if isinstance(entry, dict) and entry.get("likely_resource_type"):
                fhir_resource = entry["likely_resource_type"]
                break
        else:
            guessed = fhir_shape.get("likely_resource_type")
            if guessed:
                fhir_resource = guessed

    return {"storage": storage, "fhir_resource": fhir_resource, "terminology": None}
