"""vitals_trends tools — DB-backed (Codebase PRD §5.4).

Each tool queries TimescaleDB via the shared SQLConnector and returns FHIR R4
Observation resources (vital-signs, LOINC-coded). Same tool names / shapes as the
Day-1 stub — the swap is invisible to the agent.

Note on the time window: Synthea data is historical (readings span past months), so
`hours` is interpreted relative to the patient's LATEST reading, not wall-clock now() —
otherwise a 24h window over months-old synthetic data would always be empty.
"""

from __future__ import annotations

from backend.connectors.sql_connector import SQLConnector
from backend.shared.cache import cached

from .news2 import compute_news2

# column -> (LOINC, display, UCUM unit, normal_low, normal_high)
VITAL_META = {
    "heart_rate":    ("8867-4", "Heart rate", "/min", 51, 90),
    "resp_rate":     ("9279-1", "Respiratory rate", "/min", 12, 20),
    "spo2":          ("2708-6", "Oxygen saturation", "%", 96, 100),
    "systolic_bp":   ("8480-6", "Systolic blood pressure", "mm[Hg]", 111, 219),
    "diastolic_bp":  ("8462-4", "Diastolic blood pressure", "mm[Hg]", 60, 90),
    "temperature_c": ("8310-5", "Body temperature", "Cel", 36.1, 38.0),
}
_TREND_COLS = ["recorded_at"] + list(VITAL_META)


def _observation(patient_id, col, value, ts, interpretation=None) -> dict:
    loinc, display, unit, _, _ = VITAL_META[col]
    obs = {
        "resourceType": "Observation",
        "status": "final",
        "category": [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
            "code": "vital-signs", "display": "Vital Signs"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": loinc,
                             "display": display}], "text": display},
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": ts.isoformat() if hasattr(ts, "isoformat") else ts,
        "valueQuantity": {"value": float(value), "unit": unit,
                          "system": "http://unitsofmeasure.org", "code": unit},
    }
    if interpretation:
        obs["interpretation"] = [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
            "code": interpretation}]}]
    return obs


async def _fetch_window(conn: SQLConnector, patient_id: str, hours: int) -> list[dict]:
    """Rows within `hours` of the patient's latest reading, newest first."""
    cols = ", ".join(_TREND_COLS)
    sql = f"""
        WITH latest AS (SELECT max(recorded_at) AS m FROM vitals WHERE patient_id = $1)
        SELECT {cols} FROM vitals, latest
        WHERE patient_id = $1
          AND recorded_at >= latest.m - make_interval(hours => $2)
        ORDER BY recorded_at DESC
    """
    return await conn.query({"sql": sql, "args": [patient_id, hours]})


@cached(ttl_seconds=30)
async def get_vitals_trend(conn: SQLConnector, patient_id: str, hours: int = 24) -> list[dict]:
    """Recent vital-sign Observations — one per (timestamp, measured vital)."""
    rows = await _fetch_window(conn, patient_id, hours)
    out: list[dict] = []
    for row in rows:
        ts = row["recorded_at"]
        for col in VITAL_META:
            v = row.get(col)
            if v is not None:
                out.append(_observation(patient_id, col, v, ts))
    return out


async def list_abnormal_vitals(conn: SQLConnector, patient_id: str, hours: int = 24) -> list[dict]:
    """Vital-sign Observations outside the normal range, flagged H/L."""
    rows = await _fetch_window(conn, patient_id, hours)
    out: list[dict] = []
    for row in rows:
        ts = row["recorded_at"]
        for col, (_, _, _, lo, hi) in VITAL_META.items():
            v = row.get(col)
            if v is None:
                continue
            if v < lo:
                out.append(_observation(patient_id, col, v, ts, interpretation="L"))
            elif v > hi:
                out.append(_observation(patient_id, col, v, ts, interpretation="H"))
    return out


async def compute_news2_score(conn: SQLConnector, patient_id: str) -> dict:
    """NEWS2 from the patient's latest vitals reading (published NHS algorithm)."""
    rows = await conn.query({"sql": """
        SELECT recorded_at, heart_rate, systolic_bp, spo2, resp_rate, temperature_c
        FROM vitals WHERE patient_id = $1 ORDER BY recorded_at DESC LIMIT 1""",
        "args": [patient_id]})
    if not rows:
        return {"patient_id": patient_id, "news2_score": None,
                "risk_band": "unknown", "components": {}, "missing": ["no vitals on record"]}
    r = rows[0]
    result = compute_news2(
        resp_rate=r["resp_rate"], spo2=r["spo2"], temp=float(r["temperature_c"]) if r["temperature_c"] is not None else None,
        systolic_bp=r["systolic_bp"], heart_rate=r["heart_rate"],
        consciousness_alert=True,   # Synthea has no consciousness field; assume Alert
    )
    result["patient_id"] = patient_id
    result["as_of"] = r["recorded_at"].isoformat() if hasattr(r["recorded_at"], "isoformat") else r["recorded_at"]
    return result
