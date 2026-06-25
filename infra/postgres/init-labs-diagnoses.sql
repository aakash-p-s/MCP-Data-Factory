-- labs_diagnoses (Postgres) — Codebase PRD §7.2
CREATE TABLE IF NOT EXISTS labs (
    lab_id           SERIAL PRIMARY KEY,
    patient_id       TEXT NOT NULL,
    test_name        TEXT NOT NULL,
    loinc_code       TEXT,
    result_value     NUMERIC,
    unit             TEXT,
    reference_range  TEXT,
    abnormal_flag    TEXT,
    collected_at     TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS diagnoses (
    diagnosis_id    SERIAL PRIMARY KEY,
    patient_id      TEXT NOT NULL,
    icd10_code      TEXT,
    snomed_code     TEXT,
    description     TEXT,
    diagnosis_type  TEXT,
    onset_date      DATE
);
