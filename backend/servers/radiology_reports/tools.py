"""radiology_reports tools — GENERATED stub.

Each tool queries `radiology_reports` by patient_id and wraps rows as FHIR DocumentReference.
Specialise the SQL + FHIR shaping for production.
"""

from __future__ import annotations

from backend.connectors.sql_connector import SQLConnector

TABLE = "radiology_reports"


def _to_resource(row: dict) -> dict:
    data = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}
    return {
        "resourceType": "DocumentReference",
        "status": "current",
        "subject": {"reference": f"Patient/{row.get('patient_id')}"},
        "description": row.get("impression") or row.get("description"),
        "content": [{"attachment": {"contentType": "application/json"}}],
        "data": data,
    }


async def _query(conn: SQLConnector, patient_id: str) -> list[dict]:
    rows = await conn.query({"sql": f"SELECT * FROM {TABLE} WHERE patient_id = $1 LIMIT 50",
                             "args": [patient_id]})
    return [_to_resource(r) for r in rows]


async def get_radiology_report_trend(conn: SQLConnector, patient_id: str) -> list[dict]:
    """get_radiology_report_trend — GENERATED: returns radiology_reports rows for the patient (specialise me)."""
    return await _query(conn, patient_id)


async def get_latest_radiology_report(conn: SQLConnector, patient_id: str) -> list[dict]:
    """get_latest_radiology_report — GENERATED: returns radiology_reports rows for the patient (specialise me)."""
    return await _query(conn, patient_id)


async def search_radiology_reports_by_modality(conn: SQLConnector, patient_id: str) -> list[dict]:
    """search_radiology_reports_by_modality — GENERATED: returns radiology_reports rows for the patient (specialise me)."""
    return await _query(conn, patient_id)

