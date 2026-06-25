-- medications_interactions (Postgres) — Codebase PRD §7.3
CREATE TABLE IF NOT EXISTS medications (
    med_id       SERIAL PRIMARY KEY,
    patient_id   TEXT NOT NULL,
    drug_name    TEXT NOT NULL,
    rxnorm_code  TEXT,
    dose         TEXT,
    route        TEXT,
    frequency    TEXT,
    start_date   DATE,
    end_date     DATE,
    prescriber   TEXT
);

CREATE TABLE IF NOT EXISTS interaction_rules (
    rule_id        SERIAL PRIMARY KEY,
    rxnorm_code_a  TEXT NOT NULL,
    rxnorm_code_b  TEXT NOT NULL,
    severity       TEXT,
    description    TEXT
);
