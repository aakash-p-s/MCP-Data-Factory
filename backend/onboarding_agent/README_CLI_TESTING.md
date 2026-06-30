# Onboarding Agent — How to Run and Test (CLI)

This covers the interactive CLI (`main.py`) — discover → suggest tools →
draft RBAC → approve/reject loop. Output is always a `blueprint.yaml` file
on disk. Nothing is ever deployed by this agent.

---

## Prerequisites

```
Docker services running:  docker compose up -d
Environment loaded:       Get-Content .env | ... [Environment]::SetEnvironmentVariable
```

If you haven't done daily startup yet, do that first — this agent connects
to the same `postgres-clinical` container your 4 MCP servers already use.

---

## Part 1 — Run the agent on a known domain (no setup needed)

These 4 domains already have real tables and a frozen RBAC contract.

```bash
uv run python -m backend.onboarding_agent.main vitals_trends
uv run python -m backend.onboarding_agent.main labs_diagnoses
uv run python -m backend.onboarding_agent.main medications_interactions
uv run python -m backend.onboarding_agent.main clinical_notes_search
```

Expected:

```
Connecting to database...
✓ Schema discovered

Suggested Tools
---------------
1. get_vitals_trend
2. compute_news2_score
3. list_abnormal_vitals

Suggested RBAC
--------------
Clinical Viewer  : Allow
Physician        : Allow
Case Manager     : Deny

Approve blueprint?
0 - Approve
1 - Modify Tools
2 - Modify RBAC
3 - Cancel
>
```

Type `0`. Confirm the file landed:

```bash
cat backend/onboarding_agent/output/vitals_trends.blueprint.yaml
```

This should match `backend/servers/vitals_trends/blueprint.yaml` (Person A's real one) — that's the golden-file proof the pipeline works correctly.

---

## Part 2 — Run the golden-file test suite

Pure logic check, no database needed:

```bash
uv run pytest backend/tests/test_onboarding_agent.py -v
```

Expected: 10 passed. If any fail, something in `draft_rbac.py` was changed incorrectly — stop and check before testing new domains.

---

## Part 3 — Add `radiology_reports` as a new test domain

This is a domain that does **not** exist in the frozen 4 — used to test the
"new domain" path: heuristic FHIR inference, conservative RBAC defaults,
and the manual override/feedback loop.

### Step 1 — Create the table

```bash
docker exec -it postgres-clinical psql -U postgres -d clinical
```

Inside `psql`:

```sql
CREATE TABLE radiology_reports (
    patient_id TEXT NOT NULL,
    report_date TIMESTAMPTZ NOT NULL,
    modality TEXT,
    finding TEXT,
    severity TEXT
);

INSERT INTO radiology_reports (patient_id, report_date, modality, finding, severity)
VALUES ('080b069b-5108-46b6-ecef-6aacd3b9ef3f', now(), 'CT Chest', 'No acute findings', 'normal');

\q
```

### Step 2 — Register it in the egress guard

Open `backend/shared/egress_guard.py`. Find `_SQL_BACKENDS` and add one
line, reusing the existing `CLINICAL_DB_URL` since it's in the same
database:

```python
_SQL_BACKENDS = {
    "vitals_trends": ("VITALS_DB_URL", "postgresql://postgres:changeme@localhost:5433/vitals"),
    "labs_diagnoses": ("CLINICAL_DB_URL", "postgresql://postgres:changeme@localhost:5434/clinical"),
    "medications_interactions": ("CLINICAL_DB_URL", "postgresql://postgres:changeme@localhost:5434/clinical"),
    "radiology_reports": ("CLINICAL_DB_URL", "postgresql://postgres:changeme@localhost:5434/clinical"),  # NEW
}
```

No `.env` change needed — `CLINICAL_DB_URL` already exists.

### Step 3 — Verify it's reachable

```bash
docker exec postgres-clinical psql -U postgres -d clinical -c "\dt"
```

Confirm `radiology_reports` is listed.

### Step 4 — Run the agent against it

```bash
uv run python -m backend.onboarding_agent.main radiology_reports
```

This is the path that exercises:
- New-domain FHIR-shape heuristic (table/column name → `DiagnosticReport`)
- Conservative RBAC default (`clinical-viewer: limited`)
- `metadata_source: llm_inferred` in the audit file

---

## Part 4 — Sample CLI session, with feedback

Full example of a real run, including using "Modify Tools" with feedback
and "Modify RBAC":

```
$ uv run python -m backend.onboarding_agent.main radiology_reports

Connecting to database...
✓ Schema discovered

Discovered FHIR Shape (heuristic — confirmed/corrected by LLM next)
---------------------------------------------------------------------
  radiology_reports -> likely resourceType: DiagnosticReport
    patient_id           -> subject
    report_date          -> effectiveDateTime
    modality              -> category
    finding               -> conclusion
    severity              -> interpretation

Inferred Metadata (new domain — please verify)
-----------------------------------------------
Storage       : postgres
FHIR Resource : DiagnosticReport
Terminology   : none

Suggested Tools
---------------
1. get_radiology_reports_trend
2. get_active_radiology_reports
3. search_radiology_reports_by_finding

Suggested RBAC
--------------
Clinical Viewer  : Limited
Physician        : Allow
Case Manager     : Deny

Approve blueprint?
0 - Approve
1 - Modify Tools
2 - Modify RBAC
3 - Cancel
> 1

What is wrong with the current tools? (this feedback goes back to the LLM)
Feedback: change the name of the tool search_radiology_reports_by_finding to reports_by_finding

Regenerating tools with your feedback...

Suggested Tools
---------------
1. get_radiology_reports_trend
2. get_active_radiology_reports
3. reports_by_finding

Suggested RBAC
--------------
Clinical Viewer  : Limited
Physician        : Allow
Case Manager     : Deny

Approve blueprint?
0 - Approve
1 - Modify Tools
2 - Modify RBAC
3 - Cancel
> 2

Valid levels: allow, deny, limited
Clinical Viewer [limited]: allow
Physician [allow]:
Case Manager [deny]:

Suggested Tools
---------------
1. get_radiology_reports_trend
2. get_active_radiology_reports
3. reports_by_finding

Suggested RBAC
--------------
Clinical Viewer  : Allow
Physician        : Allow
Case Manager     : Deny

Approve blueprint?
0 - Approve
1 - Modify Tools
2 - Modify RBAC
3 - Cancel
> 0

Approved. Blueprint written to: backend/onboarding_agent/output/radiology_reports.blueprint.yaml
Next: hand off to the hardened template build step (Person A's pipeline).
```

---

## More feedback examples to try

```
Feedback: add a tool to filter findings by severity level

Feedback: rename get_radiology_reports_trend to get_radiology_history

Feedback: the third tool should do a semantic search over the finding text, not just list abnormal results

Feedback: make sure every tool requires patient_id as the first argument
```

Each one re-triggers the LLM call with your exact wording plus the
previously-rejected tool list, so it course-corrects rather than guessing
blind again.

---

## Part 5 — What to check after approving

```bash
cat backend/onboarding_agent/output/radiology_reports.blueprint.yaml
```

Should contain `storage: postgres`, `fhir_resource: DiagnosticReport` — not
`unknown` for either.

```bash
cat backend/onboarding_agent/output/radiology_reports.discovery.yaml
```

Should contain both `raw:` (actual columns) and `fhir_shape:` (the
heuristic mapping), plus `metadata_source: llm_inferred`.

---

## Part 6 — Test the typo / unknown-domain path

```bash
uv run python -m backend.onboarding_agent.main radiology_rep
```

Expected — a clean message, no traceback, terminal stays usable:

```
Connecting to database...

✗ 'radiology_rep' is not a registered domain. Check for typos, or if
this is a genuinely new domain, register it first in
backend/shared/egress_guard.py (see backend/onboarding_agent/README.md).

Tip: known domains right now are vitals_trends, labs_diagnoses,
medications_interactions, clinical_notes_search — or any domain
you've already registered in egress_guard.py.
```

---

## Part 7 — Test the RBAC typo-recovery path

```bash
uv run python -m backend.onboarding_agent.main radiology_reports
```

At the menu, type `2`, then deliberately type something invalid:

```
Valid levels: allow, deny, limited
Clinical Viewer [limited]: allow
Physician [allow]: allow
Case Manager [deny]: denny

  invalid access level 'denny'; must be one of ('allow', 'deny', 'limited') — try again.
Case Manager [deny]: deny
```

Confirms it re-prompts that one field instead of crashing the whole
session.

---

## Quick checklist — full test pass

| Step | Command | Confirms |
|---|---|---|
| 1 | `pytest backend/tests/test_onboarding_agent.py -v` | RBAC logic correct, 10/10 pass |
| 2 | `main.py vitals_trends` → approve | Golden domain works end to end |
| 3 | Create `radiology_reports` table + register in `egress_guard.py` | New domain prerequisites met |
| 4 | `main.py radiology_reports` → approve as-is | New domain discovery + inference works |
| 5 | `main.py radiology_reports` → option 1 with feedback | Tool revision loop works |
| 6 | `main.py radiology_reports` → option 2 with a typo | RBAC retry-on-invalid works |
| 7 | `main.py radiology_rep` (typo domain) | Unknown-domain error is graceful, not a crash |
| 8 | `cat output/radiology_reports.blueprint.yaml` | No `unknown` values, correct FHIR resource |
