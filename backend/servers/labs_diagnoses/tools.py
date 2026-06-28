"""labs_diagnoses tools — DB-backed (Codebase PRD §5.4).

Queries the `clinical` Postgres DB via the shared SQLConnector and returns FHIR R4
Observation (labs, LOINC) and Condition (diagnoses, SNOMED/ICD-10) resources.
"""

from __future__ import annotations

from backend.connectors.sql_connector import SQLConnector


def _lab_observation(row: dict) -> dict:
    obs = {
        "resourceType": "Observation",
        "status": "final",
        "category": [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
            "code": "laboratory", "display": "Laboratory"}]}],
        "code": {"coding": ([{"system": "http://loinc.org", "code": row["loinc_code"],
                              "display": row["test_name"]}] if row.get("loinc_code") else []),
                 "text": row["test_name"]},
        "subject": {"reference": f"Patient/{row['patient_id']}"},
        "effectiveDateTime": row["collected_at"].isoformat() if hasattr(row["collected_at"], "isoformat") else row["collected_at"],
    }
    if row.get("result_value") is not None:
        obs["valueQuantity"] = {"value": float(row["result_value"]), "unit": row.get("unit"),
                                "system": "http://unitsofmeasure.org", "code": row.get("unit")}
    if row.get("reference_range"):
        obs["referenceRange"] = [{"text": row["reference_range"]}]
    if row.get("abnormal_flag"):
        obs["interpretation"] = [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
            "code": row["abnormal_flag"]}]}]
    return obs


def _condition(row: dict) -> dict:
    coding = []
    if row.get("snomed_code"):
        coding.append({"system": "http://snomed.info/sct", "code": row["snomed_code"],
                       "display": row.get("description")})
    if row.get("icd10_code"):
        coding.append({"system": "http://hl7.org/fhir/sid/icd-10", "code": row["icd10_code"]})
    status = row.get("diagnosis_type") or "active"
    return {
        "resourceType": "Condition",
        "clinicalStatus": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
            "code": status}]},
        "code": {"coding": coding, "text": row.get("description")},
        "subject": {"reference": f"Patient/{row['patient_id']}"},
        "onsetDateTime": row["onset_date"].isoformat() if row.get("onset_date") and hasattr(row["onset_date"], "isoformat") else row.get("onset_date"),
    }


async def get_lab_trend(conn: SQLConnector, patient_id: str, test_name: str | None = None) -> list[dict]:
    """Lab Observations for a patient, newest first; optional case-insensitive test filter."""
    if test_name:
        sql = ("SELECT patient_id, test_name, loinc_code, result_value, unit, reference_range, "
               "abnormal_flag, collected_at FROM labs WHERE patient_id = $1 "
               "AND test_name ILIKE $2 ORDER BY collected_at DESC")
        args = [patient_id, f"%{test_name}%"]
    else:
        sql = ("SELECT patient_id, test_name, loinc_code, result_value, unit, reference_range, "
               "abnormal_flag, collected_at FROM labs WHERE patient_id = $1 "
               "ORDER BY collected_at DESC")
        args = [patient_id]
    rows = await conn.query({"sql": sql, "args": args})
    return [_lab_observation(r) for r in rows]


async def get_active_diagnoses(conn: SQLConnector, patient_id: str) -> list[dict]:
    """Conditions that are clinically active (diagnosis_type='active'), newest onset first."""
    rows = await conn.query({"sql":
        "SELECT patient_id, icd10_code, snomed_code, description, diagnosis_type, onset_date "
        "FROM diagnoses WHERE patient_id = $1 AND diagnosis_type = 'active' "
        "ORDER BY onset_date DESC NULLS LAST", "args": [patient_id]})
    return [_condition(r) for r in rows]


async def get_diagnosis_history(conn: SQLConnector, patient_id: str) -> list[dict]:
    """All Conditions for a patient (active + resolved), ordered by onset date."""
    rows = await conn.query({"sql":
        "SELECT patient_id, icd10_code, snomed_code, description, diagnosis_type, onset_date "
        "FROM diagnoses WHERE patient_id = $1 ORDER BY onset_date ASC NULLS LAST",
        "args": [patient_id]})
    return [_condition(r) for r in rows]
