"""Synthea data pipeline — Codebase PRD §5.1.

Generates synthetic FHIR R4 patients with a FIXED seed, then loads them into the
three data stores Person A owns:

    vitals  (TimescaleDB)            <- Observation(vital-signs)
    labs    (Postgres/clinical)      <- Observation(laboratory)
    diagnoses (Postgres/clinical)    <- Condition
    medications (Postgres/clinical)  <- MedicationRequest

Notes (DocumentReference -> Qdrant) are implemented in embed_and_load_notes() but
SKIPPED by default — the sprint schedule defers clinical_notes_search to Jul 6.
Set LOAD_NOTES=true to run them (pulls the all-MiniLM-L6-v2 embedding model).

Determinism (gap fix): a fixed SYNTHEA_SEED means the same patients regenerate on
every reseed; write_demo_aliases() then maps friendly IDs (demo-patient-1, ...) to
the real generated UUIDs so the demo can reference "the same patient" across runs.

Run inside the project venv with the data stores up:
    uv run python infra/synthea/load_patients.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg

# --- config (from .env / environment) ---------------------------------------
SEED = int(os.getenv("SYNTHEA_SEED", "42"))
PATIENT_COUNT = int(os.getenv("SYNTHEA_PATIENT_COUNT", "20"))
VITALS_DB_URL = os.environ["VITALS_DB_URL"]
CLINICAL_DB_URL = os.environ["CLINICAL_DB_URL"]
# EMBEDDING_MODEL lives in backend/shared/embeddings.py (single source of truth) —
# imported lazily in embed_and_load_notes() so the model name can never drift.
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
LOAD_NOTES = os.getenv("LOAD_NOTES", "false").lower() in ("1", "true", "yes")

SYNTHEA_DIR = Path(__file__).resolve().parent
JAR = SYNTHEA_DIR / "synthea-with-dependencies.jar"
OUTPUT_DIR = SYNTHEA_DIR / "output"
ALIASES_FILE = SYNTHEA_DIR / "demo_patient_aliases.json"

# LOINC -> vitals column. Synthea emits a blood-pressure panel (85354-9) whose
# components carry systolic (8480-6) and diastolic (8462-4).
VITAL_LOINC = {
    "8867-4": "heart_rate",
    "9279-1": "resp_rate",
    "2708-6": "spo2",
    "59408-5": "spo2",
    "8310-5": "temperature_c",
    "8480-6": "systolic_bp",
    "8462-4": "diastolic_bp",
}
BP_PANEL_LOINC = "85354-9"


# --- 1. generate -------------------------------------------------------------
def run_synthea(patient_count: int = PATIENT_COUNT, seed: int = SEED) -> Path:
    """Invoke the Synthea jar with a FIXED seed; return the FHIR output dir."""
    if not JAR.exists():
        sys.exit(
            f"Synthea jar not found at {JAR}. Download it first:\n"
            "  curl -sL -o infra/synthea/synthea-with-dependencies.jar \\\n"
            "    https://github.com/synthetichealth/synthea/releases/download/"
            "master-branch-latest/synthea-with-dependencies.jar"
        )
    cmd = [
        "java", "-jar", str(JAR),
        "-p", str(patient_count),
        "-s", str(seed),                       # population seed (determinism)
        "-cs", str(seed),                      # clinician seed (determinism)
        "--exporter.baseDirectory", str(OUTPUT_DIR),
        "--exporter.fhir.export", "true",
        "--exporter.clinical_note.export", "true",   # generate note text (default off)
        "--exporter.fhir.use_us_core_ig", "false",
        "--exporter.hospital.fhir.export", "false",
        "--exporter.practitioner.fhir.export", "false",
        "--exporter.csv.export", "false",
        "--generate.only_alive_patients", "true",
    ]
    print(f"[synthea] generating {patient_count} patients, seed={seed} ...")
    subprocess.run(cmd, check=True, cwd=str(SYNTHEA_DIR))
    fhir_dir = OUTPUT_DIR / "fhir"
    print(f"[synthea] FHIR bundles in {fhir_dir}")
    return fhir_dir


def iter_bundles(fhir_dir: Path):
    """Yield (patient_id, list_of_resources) per generated patient bundle."""
    for path in sorted(fhir_dir.glob("*.json")):
        # skip the aggregated hospital/practitioner information bundles
        if path.name.startswith(("hospitalInformation", "practitionerInformation")):
            continue
        bundle = json.loads(path.read_text(encoding="utf-8"))
        entries = [e.get("resource", {}) for e in bundle.get("entry", [])]
        patient = next((r for r in entries if r.get("resourceType") == "Patient"), None)
        if not patient:
            continue
        yield patient["id"], entries


# --- helpers -----------------------------------------------------------------
def _loinc(resource: dict) -> str | None:
    for coding in resource.get("code", {}).get("coding", []):
        if coding.get("system", "").endswith("loinc.org"):
            return coding.get("code")
    return None


def _coding(resource: dict, system_suffix: str) -> tuple[str | None, str | None]:
    for coding in resource.get("code", {}).get("coding", []):
        if system_suffix in coding.get("system", ""):
            return coding.get("code"), coding.get("display")
    return None, None


# --- 2. load vitals ----------------------------------------------------------
def load_vitals(entries: list[dict], patient_id: str, conn: psycopg.Connection) -> int:
    """Group Observation(vital-signs) by timestamp into one wide vitals row."""
    rows: dict[str, dict] = {}
    for r in entries:
        if r.get("resourceType") != "Observation":
            continue
        cats = {c.get("code") for cat in r.get("category", []) for c in cat.get("coding", [])}
        if "vital-signs" not in cats:
            continue
        ts = r.get("effectiveDateTime")
        if not ts:
            continue
        row = rows.setdefault(ts, {})
        code = _loinc(r)
        if code == BP_PANEL_LOINC:
            for comp in r.get("component", []):
                ccode = next((c.get("code") for c in comp.get("code", {}).get("coding", [])
                              if c.get("system", "").endswith("loinc.org")), None)
                col = VITAL_LOINC.get(ccode)
                val = comp.get("valueQuantity", {}).get("value")
                if col and val is not None:
                    row[col] = val
        elif code in VITAL_LOINC:
            val = r.get("valueQuantity", {}).get("value")
            if val is not None:
                row[VITAL_LOINC[code]] = val
                row.setdefault("loinc_code", code)

    inserted = 0
    cols = ("heart_rate", "systolic_bp", "diastolic_bp", "spo2", "resp_rate", "temperature_c")
    with conn.cursor() as cur:
        for ts, row in rows.items():
            # skip timestamps that only carried non-NEWS2 vitals (height/weight/BMI)
            if not any(row.get(c) is not None for c in cols):
                continue
            cur.execute(
                """INSERT INTO vitals (patient_id, recorded_at, heart_rate, systolic_bp,
                       diastolic_bp, spo2, resp_rate, temperature_c, loinc_code)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (patient_id, recorded_at) DO NOTHING""",
                (patient_id, ts,
                 _i(row.get("heart_rate")), _i(row.get("systolic_bp")),
                 _i(row.get("diastolic_bp")), _i(row.get("spo2")),
                 _i(row.get("resp_rate")), row.get("temperature_c"),
                 row.get("loinc_code")),
            )
            inserted += 1
    return inserted


def _i(v):
    return int(round(v)) if isinstance(v, (int, float)) else None


# --- 3. load labs + diagnoses ------------------------------------------------
def load_labs_and_diagnoses(entries: list[dict], patient_id: str,
                            conn: psycopg.Connection) -> tuple[int, int]:
    labs = dx = 0
    with conn.cursor() as cur:
        for r in entries:
            rt = r.get("resourceType")
            if rt == "Observation":
                cats = {c.get("code") for cat in r.get("category", []) for c in cat.get("coding", [])}
                if "laboratory" not in cats:
                    continue
                code, display = _coding(r, "loinc.org")
                vq = r.get("valueQuantity", {})
                interp = None
                for it in r.get("interpretation", []):
                    for c in it.get("coding", []):
                        interp = c.get("code")
                ref = None
                for rr in r.get("referenceRange", []):
                    ref = rr.get("text") or ref
                cur.execute(
                    """INSERT INTO labs (patient_id, test_name, loinc_code, result_value,
                           unit, reference_range, abnormal_flag, collected_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (patient_id, display or r.get("code", {}).get("text") or "unknown",
                     code, vq.get("value"), vq.get("unit"), ref, interp,
                     r.get("effectiveDateTime")),
                )
                labs += 1
            elif rt == "Condition":
                snomed, desc = _coding(r, "snomed")
                icd10, _ = _coding(r, "icd")
                clinical = None
                for c in r.get("clinicalStatus", {}).get("coding", []):
                    clinical = c.get("code")
                onset = r.get("onsetDateTime")
                cur.execute(
                    """INSERT INTO diagnoses (patient_id, icd10_code, snomed_code,
                           description, diagnosis_type, onset_date)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (patient_id, icd10, snomed,
                     desc or r.get("code", {}).get("text"), clinical,
                     onset[:10] if onset else None),
                )
                dx += 1
    return labs, dx


# --- 4. load medications -----------------------------------------------------
def load_medications(entries: list[dict], patient_id: str,
                     conn: psycopg.Connection) -> int:
    meds = 0
    with conn.cursor() as cur:
        for r in entries:
            if r.get("resourceType") != "MedicationRequest":
                continue
            cc = r.get("medicationCodeableConcept", {})
            rxnorm = drug = None
            for c in cc.get("coding", []):
                if "rxnorm" in c.get("system", ""):
                    rxnorm = c.get("code")
                    drug = c.get("display")
            drug = drug or cc.get("text") or "unknown"
            dose = route = freq = None
            di = (r.get("dosageInstruction") or [{}])[0]
            for dr in di.get("doseAndRate", []):
                q = dr.get("doseQuantity", {})
                if q:
                    dose = f"{q.get('value')} {q.get('unit', '')}".strip()
            route = di.get("route", {}).get("text")
            timing = di.get("timing", {}).get("code", {})
            freq = timing.get("text")
            authored = r.get("authoredOn")
            cur.execute(
                """INSERT INTO medications (patient_id, drug_name, rxnorm_code, dose,
                       route, frequency, start_date, end_date, prescriber)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (patient_id, drug, rxnorm, dose, route, freq,
                 authored[:10] if authored else None, None, None),
            )
            meds += 1
    return meds


# --- 5. notes -> Qdrant (deferred to Jul 6 unless LOAD_NOTES=true) -----------
def embed_and_load_notes(fhir_dir: Path) -> int:
    """Read Synthea consultation notes, embed, upsert into Qdrant.

    Notes are exported (with --exporter.clinical_note.export) as one .txt per patient
    under output/notes/, named <...>_<patient_uuid>.txt — the trailing UUID matches the
    patient_id stored in the SQL tables. Each file holds one or more encounter notes,
    delimited by a bare date line; we split on that so each encounter is its own note.

    Tagged physician_note/physician by default (notes are written from the provider's
    perspective). Model + collection come from backend/shared/embeddings.py — the SAME
    source the vector connector imports — so loader and query can never drift, and
    ensure_collection() stamps the model so a mismatch is caught loudly.
    """
    import re
    import sys

    # repo root on sys.path so `backend.shared` imports when run as a script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from qdrant_client import QdrantClient
    from qdrant_client.models import PointStruct

    from backend.shared.embeddings import COLLECTION, embed, ensure_collection

    notes_dir = fhir_dir.parent / "notes"
    if not notes_dir.is_dir():
        print(f"[notes] no notes dir at {notes_dir} — run with clinical_note export enabled")
        return 0

    client = QdrantClient(url=QDRANT_URL)
    ensure_collection(client)   # (re)create collection + stamp embedding fingerprint

    date_re = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)
    points: list[PointStruct] = []
    point_id = 1                # id 0 is reserved for the fingerprint meta point
    for nf in sorted(notes_dir.glob("*.txt")):
        patient_id = nf.stem.split("_")[-1]          # trailing UUID == Patient.id
        content = nf.read_text(errors="ignore")
        # split into per-encounter notes on bare date-header lines
        marks = list(date_re.finditer(content))
        chunks = ([(m.group(1), content[m.start():(marks[i + 1].start() if i + 1 < len(marks) else len(content))])
                   for i, m in enumerate(marks)] or [(None, content)])
        for note_date, text in chunks:
            text = text.strip()
            if not text:
                continue
            points.append(PointStruct(
                id=point_id,
                vector=embed(text),
                payload={
                    "patient_id": patient_id,
                    "note_date": note_date,
                    "author": "physician",
                    "note_type": "physician_note",
                    "author_role": "physician",
                    "text": text[:2000],
                },
            ))
            point_id += 1
    if points:
        client.upsert(COLLECTION, points=points)
    print(f"[notes] embedded + upserted {len(points)} notes into Qdrant ({COLLECTION})")
    return len(points)


# --- 6. demo aliases (determinism gap fix) -----------------------------------
def write_demo_aliases(patient_ids: list[str]) -> Path:
    aliases = {f"demo-patient-{i+1}": pid for i, pid in enumerate(sorted(patient_ids))}
    ALIASES_FILE.write_text(json.dumps(aliases, indent=2) + "\n")
    print(f"[aliases] wrote {len(aliases)} -> {ALIASES_FILE}")
    return ALIASES_FILE


def _truncate(vconn: psycopg.Connection, cconn: psycopg.Connection) -> None:
    """Clean slate so a reseed with the same SYNTHEA_SEED is reproducible."""
    with vconn.cursor() as cur:
        cur.execute("TRUNCATE vitals")
    with cconn.cursor() as cur:
        cur.execute("TRUNCATE labs, diagnoses, medications RESTART IDENTITY")


# --- orchestration -----------------------------------------------------------
def main() -> None:
    fhir_dir = run_synthea()

    patient_ids: list[str] = []
    totals = {"vitals": 0, "labs": 0, "diagnoses": 0, "medications": 0}

    with psycopg.connect(VITALS_DB_URL) as vconn, psycopg.connect(CLINICAL_DB_URL) as cconn:
        _truncate(vconn, cconn)
        for patient_id, entries in iter_bundles(fhir_dir):
            patient_ids.append(patient_id)
            totals["vitals"] += load_vitals(entries, patient_id, vconn)
            labs, dx = load_labs_and_diagnoses(entries, patient_id, cconn)
            totals["labs"] += labs
            totals["diagnoses"] += dx
            totals["medications"] += load_medications(entries, patient_id, cconn)
        vconn.commit()
        cconn.commit()

    write_demo_aliases(patient_ids)

    if LOAD_NOTES:
        embed_and_load_notes(fhir_dir)
    else:
        print("[notes] skipped (set LOAD_NOTES=true to embed clinical notes — Jul 6 task)")

    print(f"[done] {len(patient_ids)} patients | "
          + " ".join(f"{k}={v}" for k, v in totals.items()))


if __name__ == "__main__":
    main()
