-- vitals (TimescaleDB) — Codebase PRD §7.1
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS vitals (
    patient_id     TEXT NOT NULL,
    recorded_at    TIMESTAMPTZ NOT NULL,
    heart_rate     INT,
    systolic_bp    INT,
    diastolic_bp   INT,
    spo2           INT,
    resp_rate      INT,
    temperature_c  NUMERIC(4,1),
    loinc_code     TEXT,
    PRIMARY KEY (patient_id, recorded_at)
);

SELECT create_hypertable('vitals', 'recorded_at', if_not_exists => TRUE);
