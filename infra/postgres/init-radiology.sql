-- radiology_reports — a NEW data source onboarded via the factory pattern (demo).
CREATE TABLE IF NOT EXISTS radiology_reports (
    report_id   SERIAL PRIMARY KEY,
    patient_id  TEXT NOT NULL,
    modality    TEXT,
    body_site   TEXT,
    loinc_code  TEXT,
    impression  TEXT,
    report_date DATE
);
TRUNCATE radiology_reports RESTART IDENTITY;
INSERT INTO radiology_reports (patient_id, modality, body_site, loinc_code, impression, report_date) VALUES
 ('080b069b-5108-46b6-ecef-6aacd3b9ef3f','CT','Chest','24627-2','No acute cardiopulmonary process. Mild coronary artery calcification.','2026-03-12'),
 ('080b069b-5108-46b6-ecef-6aacd3b9ef3f','XR','Chest','36643-5','Stable cardiomegaly. No effusion or consolidation.','2025-11-04'),
 ('2c167999-289d-95fa-5c27-7d8b8d35348c','MRI','Brain','24590-2','No acute infarct. Age-appropriate involutional changes.','2026-01-20');
