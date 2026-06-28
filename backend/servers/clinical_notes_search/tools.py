"""clinical_notes_search tools — Qdrant-backed (Codebase PRD §5.4).

Queries the clinical_notes collection via VectorConnector and returns FHIR R4
DocumentReference resources. Payload fields match infra/synthea/load_patients.py.
"""

from __future__ import annotations

from backend.connectors.vector_connector import VectorConnector
from backend.shared.cache import cached


def _document_reference(row: dict) -> dict:
    patient_id = row["patient_id"]
    note_type = row.get("note_type") or "clinical_note"
    text = row.get("text") or ""
    return {
        "resourceType": "DocumentReference",
        "id": str(row.get("id", "")),
        "status": "current",
        "type": {"text": note_type},
        "subject": {"reference": f"Patient/{patient_id}"},
        "date": row.get("note_date"),
        "author": [{"display": row.get("author") or row.get("author_role") or "unknown"}],
        "description": text[:500] if text else None,
        "content": [{
            "attachment": {
                "contentType": "text/plain",
                "title": note_type.replace("_", " ").title(),
            },
        }],
        "text": text,
    }


async def semantic_search_notes(
    conn: VectorConnector, patient_id: str, query: str, limit: int = 5,
) -> list[dict]:
    """Semantic similarity search over a patient's notes (embedded query vs Qdrant)."""
    rows = await conn.query({
        "mode": "search",
        "patient_id": patient_id,
        "query_text": query,
        "limit": limit,
    })
    return [_document_reference(r) for r in rows]


@cached(ttl_seconds=30)
async def get_recent_notes(
    conn: VectorConnector, patient_id: str, limit: int = 5,
) -> list[dict]:
    """Most recent clinical notes for a patient (by note_date, not vector rank)."""
    rows = await conn.query({
        "mode": "recent",
        "patient_id": patient_id,
        "limit": limit,
    })
    return [_document_reference(r) for r in rows]


async def get_notes_by_type(
    conn: VectorConnector, patient_id: str, note_type: str, limit: int = 10,
) -> list[dict]:
    """Notes filtered by note_type payload (e.g. physician_note)."""
    rows = await conn.query({
        "mode": "by_type",
        "patient_id": patient_id,
        "note_type": note_type,
        "limit": limit,
    })
    return [_document_reference(r) for r in rows]
