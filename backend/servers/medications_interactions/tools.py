"""medications_interactions tools — DB-backed (Codebase PRD §5.4).

Queries the `clinical` Postgres DB via SQLConnector. Returns FHIR R4 MedicationStatement
for the med list; interactions + polypharmacy are plain dicts (analytic outputs).
Active meds are deduped to one row per RxNorm code (most recent) so refills of the same
drug aren't counted as polypharmacy.
"""

from __future__ import annotations

from backend.connectors.sql_connector import SQLConnector

from . import interactions

POLYPHARMACY_THRESHOLD = 5

# one row per distinct drug (latest), only "active" (no end_date or future)
_ACTIVE_MEDS_SQL = """
    SELECT DISTINCT ON (rxnorm_code)
           patient_id, drug_name, rxnorm_code, dose, route, frequency, start_date
    FROM medications
    WHERE patient_id = $1 AND (end_date IS NULL OR end_date > now())
    ORDER BY rxnorm_code, start_date DESC NULLS LAST
"""


def _medication_statement(row: dict) -> dict:
    dosage = " ".join(x for x in (row.get("dose"), row.get("route"), row.get("frequency")) if x)
    ms = {
        "resourceType": "MedicationStatement",
        "status": "active",
        "medicationCodeableConcept": {
            "coding": ([{"system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                         "code": row["rxnorm_code"], "display": row["drug_name"]}]
                       if row.get("rxnorm_code") else []),
            "text": row["drug_name"]},
        "subject": {"reference": f"Patient/{row['patient_id']}"},
    }
    if row.get("start_date"):
        ms["effectiveDateTime"] = row["start_date"].isoformat() if hasattr(row["start_date"], "isoformat") else row["start_date"]
    if dosage:
        ms["dosage"] = [{"text": dosage}]
    return ms


async def _active_rows(conn: SQLConnector, patient_id: str) -> list[dict]:
    return await conn.query({"sql": _ACTIVE_MEDS_SQL, "args": [patient_id]})


async def get_active_medications(conn: SQLConnector, patient_id: str) -> list[dict]:
    """Active medications as FHIR MedicationStatement (one per distinct drug)."""
    return [_medication_statement(r) for r in await _active_rows(conn, patient_id)]


async def check_drug_interactions(conn: SQLConnector, patient_id: str) -> list[dict]:
    """Pairwise interactions among the patient's active meds (curated RxNorm rule set)."""
    rows = await _active_rows(conn, patient_id)
    by_code = {r["rxnorm_code"]: r["drug_name"] for r in rows if r.get("rxnorm_code")}
    hits = await interactions.check_pairs(conn, list(by_code))
    return [{
        "severity": h["severity"],
        "description": h["description"],
        "drug_a": {"rxnorm_code": h["rxnorm_code_a"], "drug_name": by_code.get(h["rxnorm_code_a"])},
        "drug_b": {"rxnorm_code": h["rxnorm_code_b"], "drug_name": by_code.get(h["rxnorm_code_b"])},
        "disclaimer": "Illustrative curated rule set — not a licensed clinical drug database.",
    } for h in hits]


async def get_polypharmacy_risk(conn: SQLConnector, patient_id: str) -> dict:
    """Count of distinct active meds; 5+ flags elevated polypharmacy risk."""
    rows = await _active_rows(conn, patient_id)
    n = len(rows)
    return {
        "patient_id": patient_id,
        "active_medication_count": n,
        "threshold": POLYPHARMACY_THRESHOLD,
        "risk": "elevated" if n >= POLYPHARMACY_THRESHOLD else "normal",
    }
