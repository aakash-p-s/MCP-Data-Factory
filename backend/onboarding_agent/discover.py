"""
backend/onboarding_agent/discover.py

Stage 1 of 4 - Discovery (Codebase PRD section 5.5 / ONBOARDING_AGENT.md /
Person B PRD section 5.4: "discover.py - reads the target source's schema
(FHIR shape, not just SQL columns)").

Two layers:

  1. Raw introspection - reuses Person A's existing Connector ABC via
     egress_guard.locked_connector_for(). No new DB code is written here.
     Returns whatever shape that connector's schema() already produces
     (SQLConnector: {table: [{column, type}, ...]}; VectorConnector:
     {collection, vector_size, payload_fields}).

  2. FHIR-shape interpretation - maps each discovered table/column onto a
     best-guess FHIR R4 resource + field mapping, BEFORE handing off to
     suggest_tools.py. This is what makes discovery FHIR-aware per the PRD
     wording, rather than deferring all clinical interpretation to the LLM
     tool-suggestion stage one step later.

The raw schema and FHIR-shaped schema are both returned - downstream stages
(suggest_tools, assemble_blueprint) can use whichever is more useful, and
the FHIR shape is what gets written into <domain>.discovery.yaml for human
review.
"""

from __future__ import annotations

import logging
import re

from backend.shared.connector_base import Connector
from backend.shared.egress_guard import locked_connector_for

logger = logging.getLogger(__name__)

# Heuristic FHIR field-name patterns - matched against discovered SQL column
# names (case-insensitive substring match) to propose a likely FHIR R4 field
# mapping WITHOUT calling an LLM for this step. Kept deterministic and cheap;
# suggest_tools.py's LLM call is still the place for anything genuinely
# ambiguous (tool design, full fhir_resource selection for the blueprint).
_FHIR_FIELD_HINTS: list[tuple[str, str]] = [
    ("patient_id", "subject"),
    ("patient", "subject"),
    ("date", "effectiveDateTime"),
    ("time", "effectiveDateTime"),
    ("recorded_at", "effectiveDateTime"),
    ("value", "valueQuantity"),
    ("result", "valueQuantity"),
    ("finding", "conclusion"),
    ("conclusion", "conclusion"),
    ("note", "presentedForm"),
    ("text", "presentedForm"),
    ("code", "code"),
    ("status", "status"),
    ("severity", "interpretation"),
    ("dose", "dosage"),
    ("drug", "medicationCodeableConcept"),
    ("medication", "medicationCodeableConcept"),
    ("diagnosis", "code"),
    ("icd", "code"),
    ("rxnorm", "code"),
    ("loinc", "code"),
    ("modality", "category"),
    # Common named vital-sign / lab-result columns (PRD example: heart_rate,
    # temperature, blood_pressure) - these are themselves the OBSERVED VALUE,
    # so they map to valueQuantity like "value"/"result" above. Listed
    # explicitly because they are extremely common real-world column names
    # that do not contain the generic substrings already covered.
    ("heart_rate", "valueQuantity"),
    ("temperature", "valueQuantity"),
    ("blood_pressure", "valueQuantity"),
    ("systolic", "valueQuantity"),
    ("diastolic", "valueQuantity"),
    ("spo2", "valueQuantity"),
    ("oxygen_sat", "valueQuantity"),
    ("respiratory_rate", "valueQuantity"),
    ("resp_rate", "valueQuantity"),
    ("pulse", "valueQuantity"),
    ("weight", "valueQuantity"),
    ("height", "valueQuantity"),
    ("bmi", "valueQuantity"),
    ("glucose", "valueQuantity"),
    ("creatinine", "valueQuantity"),
    ("hemoglobin", "valueQuantity"),
    ("cholesterol", "valueQuantity"),
]

# Resource-shape heuristics - table-name substring -> likely FHIR resource.
# Used only as a fallback hint here; suggest_tools.suggest_tools_and_metadata()
# still makes the final, LLM-reasoned fhir_resource choice for the blueprint
# (it sees the full schema + can reason about ambiguous cases this simple
# substring match cannot).
_RESOURCE_NAME_HINTS: list[tuple[str, str]] = [
    ("vital", "Observation"),
    ("lab", "Observation"),
    ("observation", "Observation"),
    ("diagnos", "Condition"),
    ("condition", "Condition"),
    ("medication", "MedicationStatement"),
    ("drug", "MedicationStatement"),
    ("note", "DocumentReference"),
    ("report", "DiagnosticReport"),
    ("radiology", "DiagnosticReport"),
    ("imaging", "DiagnosticReport"),
    ("procedure", "Procedure"),
]

# Column-name-driven resource fallback: if the TABLE name itself gives no
# hint (e.g. a generic name like "patient_observations" or "measurements"),
# but its COLUMNS look like vital-sign/lab values, infer Observation from
# the columns instead. This closes the gap where heart_rate/temperature/
# blood_pressure-style columns sit in a table whose name alone doesn'''t
# say "vital" or "lab".
_OBSERVATION_VALUE_COLUMNS = frozenset({
    "heart_rate", "temperature", "blood_pressure", "systolic", "diastolic",
    "spo2", "oxygen_sat", "respiratory_rate", "resp_rate", "pulse",
    "weight", "height", "bmi", "glucose", "creatinine", "hemoglobin",
    "cholesterol", "value", "result",
})


def _guess_field_mapping(column_name: str) -> str | None:
    """Best-effort FHIR field guess for one SQL column name."""
    lower = column_name.lower()
    for pattern, fhir_field in _FHIR_FIELD_HINTS:
        if pattern in lower:
            return fhir_field
    return None


def _guess_resource_type(table_name: str, column_names: list[str] | None = None) -> str | None:
    """
    Best-effort FHIR resourceType guess. Tries the table name first (e.g.
    "radiology_reports" -> DiagnosticReport). If that gives nothing AND
    column_names is provided, falls back to checking whether any column
    looks like a recognized vital-sign/lab VALUE (heart_rate, temperature,
    blood_pressure, etc.) - a table named generically ("patient_observations",
    "measurements") with those columns is almost certainly Observation, even
    though its own name carries no hint.
    """
    lower = table_name.lower()
    for pattern, resource_type in _RESOURCE_NAME_HINTS:
        if pattern in lower:
            return resource_type

    if column_names:
        for col in column_names:
            if col.lower() in _OBSERVATION_VALUE_COLUMNS:
                return "Observation"

    return None


def _fhir_shape_sql_schema(raw_schema: dict) -> dict:
    """
    Turn {table: [{column, type}, ...]} into an FHIR-shaped view:

        {
          "<table>": {
            "likely_resource_type": "Observation" | None,
            "field_mapping": {"<column>": "<fhir_field>" | None, ...}
          }
        }

    This is heuristic, not authoritative - it is a STARTING POINT shown to
    the human approver and consumed by suggest_tools.py's LLM call (which
    makes the final, reasoned fhir_resource decision for the blueprint).
    """
    shaped: dict = {}
    for table_name, columns in raw_schema.items():
        if not isinstance(columns, list):
            # Non-SQL shape slipped through (shouldn't happen for SQLConnector,
            # but don't crash discovery over it) - pass through unshaped.
            shaped[table_name] = {"likely_resource_type": None, "field_mapping": {}}
            continue

        field_mapping = {}
        for col in columns:
            col_name = col.get("column") if isinstance(col, dict) else str(col)
            if col_name:
                field_mapping[col_name] = _guess_field_mapping(col_name)

        shaped[table_name] = {
            "likely_resource_type": _guess_resource_type(table_name, list(field_mapping.keys())),
            "field_mapping": field_mapping,
        }
    return shaped


def _fhir_shape_vector_schema(raw_schema: dict) -> dict:
    """
    VectorConnector.schema() already returns {"collection", "vector_size",
    "payload_fields"} - payload_fields IS effectively the FHIR-relevant field
    list already (see clinical_notes_search's real payload: patient_id,
    note_date, author, note_type, author_role, text). Map those onto FHIR
    DocumentReference fields the same way the SQL path does for columns.
    """
    payload_fields = raw_schema.get("payload_fields", [])
    field_mapping = {field: _guess_field_mapping(field) for field in payload_fields}
    return {
        "collection": raw_schema.get("collection"),
        "likely_resource_type": "DocumentReference",
        "field_mapping": field_mapping,
    }


def _is_vector_schema(raw_schema: dict) -> bool:
    return "vector_size" in raw_schema or "payload_fields" in raw_schema


async def discover_schema(connector: Connector) -> dict:
    """
    Introspect the target source via the supplied connector, then layer an
    FHIR-shape interpretation on top (PRD: "reads the target source's
    schema (FHIR shape, not just SQL columns)").

    Input:  an already-resolved Connector (SQLConnector or VectorConnector),
            typically obtained from locked_connector_for(domain).
    Output: {
              "raw": <connector's native schema() shape, unmodified>,
              "fhir_shape": <heuristic per-table/collection FHIR mapping>
            }
    """
    await connector.connect()
    raw_schema = await connector.schema()

    if _is_vector_schema(raw_schema):
        fhir_shape = _fhir_shape_vector_schema(raw_schema)
    else:
        fhir_shape = _fhir_shape_sql_schema(raw_schema)

    logger.info(
        "discover_schema: %d top-level keys discovered (FHIR-shaped)",
        len(raw_schema) if isinstance(raw_schema, dict) else 0,
    )

    return {"raw": raw_schema, "fhir_shape": fhir_shape}


class UnknownDomainError(Exception):
    """
    Raised when a domain name has no registered backend in
    backend/shared/egress_guard.py - typically a typo (e.g. "radiology_rep"
    instead of "radiology_reports") or a genuinely new domain that hasn't
    been wired up yet (Step 2 of onboarding a new domain - see README).
    Caught by main.py / run.py to show a friendly message and let the CLI
    session continue instead of crashing with a raw traceback.
    """
    def __init__(self, domain: str):
        self.domain = domain
        super().__init__(
            f"'{domain}' is not a registered domain. Check for typos, or if "
            f"this is a genuinely new domain, register it first in "
            f"backend/shared/egress_guard.py (see backend/onboarding_agent/README.md)."
        )


async def discover_domain(domain: str) -> dict:
    """
    Convenience wrapper - picks the locked connector for `domain` (one of
    vitals_trends / labs_diagnoses / medications_interactions /
    clinical_notes_search, or a newly-registered domain in
    backend/shared/egress_guard.py) and discovers its FHIR-shaped schema in
    one call.

    This is the entry point main.py / run.py use:
        schema = await discover_domain("vitals_trends")
        # schema["raw"]        -> what the connector actually returned
        # schema["fhir_shape"] -> heuristic FHIR resource/field guesses

    Raises UnknownDomainError (not the raw egress_guard KeyError) if the
    domain isn't registered - gives the caller a clean, catchable error
    with a helpful message instead of a confusing low-level KeyError.
    """
    try:
        connector = locked_connector_for(domain)
    except KeyError:
        raise UnknownDomainError(domain) from None

    try:
        return await discover_schema(connector)
    finally:
        await connector.close()
