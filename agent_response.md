# Agent Response Documentation
## Patient Risk Intelligence MCP Platform — Runtime Agent

---

## Input (same for all 3 roles)

```json
{
  "question": "What is this patient overall risk picture?",
  "patient_id": "demo-patient-1",
  "purpose_of_access": "deterioration_review"
}
```

**Patient alias resolved:** `demo-patient-1` → `080b069b-5108-46b6-ecef-6aacd3b9ef3f`

---

## Output 1 — Doctor (grp-physician)

**Servers called:** vitals_trends, labs_diagnoses, medications_interactions, clinical_notes_search

```json
{
  "answer": "The patient has an elevated polypharmacy risk with 8 active medications (medications_interactions). There is a moderate drug interaction risk between naproxen and lisinopril, which may reduce the antihypertensive effect and increase the risk of renal impairment (medications_interactions). The NEWS2 score is low at 1, with a slightly low systolic blood pressure (106 mmHg) and high diastolic blood pressure (94 mmHg) (vitals_trends). Active diagnoses include ischemic heart disease, essential hypertension, and hyperlipidemia (labs_diagnoses). Overall, the patient is at moderate risk due to polypharmacy and drug interactions, despite a low NEWS2 score.",
  "patient_id": "demo-patient-1",
  "patient_uuid": "080b069b-5108-46b6-ecef-6aacd3b9ef3f",
  "purpose_of_access": "deterioration_review",
  "servers_called": [
    "vitals_trends",
    "labs_diagnoses",
    "medications_interactions",
    "clinical_notes_search"
  ]
}
```

---

## Output 2 — Nurse (grp-clinical-viewer)

**Servers called:** vitals_trends, labs_diagnoses only
*(medications_interactions and clinical_notes_search not connected — role not permitted)*

```json
{
  "answer": "The patient has a low NEWS2 score of 1, indicating low immediate risk of deterioration (vitals_trends). However, there are significant chronic conditions, including ischemic heart disease and essential hypertension (labs_diagnoses). The patient also has a history of social isolation and unemployment, which may impact overall health (labs_diagnoses). Recent lab results show elevated creatinine levels, suggesting potential renal impairment (labs_diagnoses). Blood pressure readings show low systolic and high diastolic pressures, indicating possible cardiovascular concerns (vitals_trends). Overall, while the immediate risk is low, chronic conditions and social factors suggest a need for ongoing management and monitoring.",
  "patient_id": "demo-patient-1",
  "patient_uuid": "080b069b-5108-46b6-ecef-6aacd3b9ef3f",
  "purpose_of_access": "deterioration_review",
  "servers_called": [
    "vitals_trends",
    "labs_diagnoses"
  ]
}
```

---

## Output 3 — Case Manager (grp-case-manager)

**Servers called:** clinical_notes_search only
*(vitals_trends, labs_diagnoses, medications_interactions not connected — role not permitted)*

```json
{
  "answer": "The patient has a history of social isolation and stress, which may contribute to overall health risks (clinical_notes_search). Recent notes indicate a history of acute viral pharyngitis, viral sinusitis, and gingivitis, but no current acute complaints (clinical_notes_search). The patient is on lisinopril and simvastatin, suggesting management of hypertension and hyperlipidemia (clinical_notes_search). There are no known allergies or active medications beyond these (clinical_notes_search). No recent deterioration events or significant changes in condition are noted (clinical_notes_search). Overall, the patient's risk appears stable with chronic conditions managed, but social isolation and stress may warrant attention to prevent potential deterioration.",
  "patient_id": "demo-patient-1",
  "patient_uuid": "080b069b-5108-46b6-ecef-6aacd3b9ef3f",
  "purpose_of_access": "deterioration_review",
  "servers_called": [
    "clinical_notes_search"
  ]
}
```

---

## RBAC Matrix — Who Sees What

| Role | vitals_trends | labs_diagnoses | medications_interactions | clinical_notes_search |
|---|---|---|---|---|
| grp-physician (doctor) | ✓ | ✓ | ✓ | ✓ |
| grp-clinical-viewer (nurse) | ✓ | ✓ | ✗ | ✗ |
| grp-case-manager | ✗ | ✗ | ✗ | ✓ |

---

## Key Facts — demo-patient-1

| Field | Value |
|---|---|
| Patient name | Chester802 Aufderhar910 |
| UUID | 080b069b-5108-46b6-ecef-6aacd3b9ef3f |
| NEWS2 score | 1 (low risk) |
| Systolic BP | 106 mmHg (slightly low) |
| Diastolic BP | 94 mmHg (slightly high) |
| Active medications | 8 |
| Drug interaction | Lisinopril + Naproxen (moderate) |
| Active diagnoses | Ischemic heart disease, Essential hypertension, Hyperlipidemia |
