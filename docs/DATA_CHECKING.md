# Data Checking Guide — Browse & Verify Your Data Stores

How to inspect synthetic patient data in the browser (recommended) or from the
command line. This is **optional local tooling** — it does not change Person A or
Person B PRD scope; it only helps you verify that `load_patients.py` worked.

For full setup, see [`IMPLEMENTATION.md`](IMPLEMENTATION.md). For architecture,
see [`README.md`](../README.md).

---

## Your data stores at a glance

| Store | What's in it | Browser URL | SQL? |
| --- | --- | --- | --- |
| **TimescaleDB** | Vitals (HR, BP, SpO₂, etc.) | http://localhost:5050 (pgAdmin) | Yes |
| **Postgres** | Labs, diagnoses, medications | http://localhost:5050 (pgAdmin) | Yes |
| **Qdrant** | Clinical notes (vectors + text) | http://localhost:6333/dashboard | No |

Host ports (from `.env`): TimescaleDB **5433**, Postgres **5434**, Qdrant **6333**.

---

## Start pgAdmin (SQL browser)

pgAdmin is optional and uses the `tools` profile in `docker-compose.data.yml`.

```bash
docker compose -f docker-compose.data.yml --profile tools up -d pgadmin
```

```powershell
cd c:\Users\Bhavna\Desktop\data_factory
docker compose -f docker-compose.data.yml --profile tools up -d pgadmin
```

Wait ~30 seconds on first start, then open **http://localhost:5050**.

| Field | Value |
| --- | --- |
| Email | `admin@example.com` (or `PGADMIN_EMAIL` in `.env`) |
| Password | `changeme` (or `PGADMIN_PASSWORD` in `.env`) |

---

## Register servers in pgAdmin

pgAdmin runs **inside Docker**, so use **container hostnames** — not `localhost`.

### Vitals (TimescaleDB)

1. Right-click **Servers** → **Register** → **Server**
2. **General** → Name: `Vitals`
3. **Connection**:

| Field | Value |
| --- | --- |
| Host | `timescaledb-vitals` |
| Port | `5432` |
| Maintenance database | `vitals` |
| Username | `postgres` |
| Password | `changeme` |

4. **Save**

Browse data: **Vitals → Databases → vitals → Schemas → public → Tables → vitals**
→ right-click → **View/Edit Data → All Rows**

### Clinical (Postgres)

Same steps, new server:

| Field | Value |
| --- | --- |
| Name | `Clinical` |
| Host | `postgres-clinical` |
| Port | `5432` |
| Maintenance database | `clinical` |
| Username | `postgres` |
| Password | `changeme` |

Tables: `labs`, `diagnoses`, `medications`, `interaction_rules`

---

## Run SQL status checks (pgAdmin Query Tool)

Right-click a database → **Query Tool**, then run:

### Row counts (all patients)

```sql
-- Vitals DB
SELECT count(*) AS vitals FROM vitals;
```

```sql
-- Clinical DB
SELECT count(*) AS labs FROM labs;
SELECT count(*) AS diagnoses FROM diagnoses;
SELECT count(*) AS medications FROM medications;
```

Expected ballpark for `SYNTHEA_SEED=42` / 20 patients (counts may vary slightly
by Synthea version): vitals ~230+, labs ~2300+, diagnoses ~580+, medications ~360+.

### Sample rows

```sql
-- Vitals
SELECT patient_id, loinc_code, display, value, unit, recorded_at
FROM vitals
LIMIT 10;
```

```sql
-- Labs
SELECT patient_id, loinc_code, display, value, unit, recorded_at
FROM labs
LIMIT 10;
```

### One demo patient

Friendly IDs like `demo-patient-1` map to UUIDs in
[`infra/synthea/demo_patient_aliases.json`](../infra/synthea/demo_patient_aliases.json).

**PowerShell** — get UUID for `demo-patient-1`:

```powershell
cd c:\Users\Bhavna\Desktop\data_factory
(Get-Content infra/synthea/demo_patient_aliases.json | ConvertFrom-Json).'demo-patient-1'
```

**macOS / Linux:**

```bash
python3 -c "import json; print(json.load(open('infra/synthea/demo_patient_aliases.json'))['demo-patient-1'])"
```

Then in pgAdmin (replace `PASTE-UUID-HERE`):

```sql
SELECT count(*) AS vitals FROM vitals WHERE patient_id = 'PASTE-UUID-HERE';
```

```sql
SELECT count(*) AS labs FROM labs WHERE patient_id = 'PASTE-UUID-HERE';
SELECT count(*) AS diagnoses FROM diagnoses WHERE patient_id = 'PASTE-UUID-HERE';
SELECT count(*) AS meds FROM medications WHERE patient_id = 'PASTE-UUID-HERE';
```

---

## Qdrant dashboard (clinical notes)

Open **http://localhost:6333/dashboard** (no login).

1. Click **Collections** → `clinical_notes`
2. Browse points or filter by payload field `patient_id`

> The collection is **empty** unless you ran the loader with `LOAD_NOTES=true`
> (see [`IMPLEMENTATION.md`](IMPLEMENTATION.md) §5). After loading, expect
> ~900+ note points plus 1 fingerprint point (id `0`).

Verify from the terminal:

```bash
curl -s http://localhost:6333/collections/clinical_notes | jq .result.points_count
```

```powershell
curl.exe -s http://localhost:6333/collections/clinical_notes
```

Use the same `patient_id` UUID from `demo_patient_aliases.json` to find that
patient's notes in Qdrant.

---

## Quick CLI checks (no browser)

Useful for scripts or when pgAdmin is not running.

```bash
docker compose -f docker-compose.data.yml ps
docker exec timescaledb-vitals psql -U postgres -d vitals -c "\dt"
docker exec postgres-clinical psql -U postgres -d clinical -c "\dt"
docker exec timescaledb-vitals psql -U postgres -d vitals -c "SELECT count(*) FROM vitals;"
docker exec postgres-clinical psql -U postgres -d clinical -c "SELECT count(*) FROM labs;"
```

---

## What each table holds

| Database | Table | Content |
| --- | --- | --- |
| `vitals` | `vitals` | Heart rate, BP, temperature, SpO₂, respiratory rate |
| `clinical` | `labs` | Laboratory results (LOINC-coded) |
| `clinical` | `diagnoses` | Conditions (SNOMED / ICD) |
| `clinical` | `medications` | Prescribed medications (RxNorm) |
| `clinical` | `interaction_rules` | Drug interaction reference rules |
| Qdrant | `clinical_notes` | Physician note text + embedding vectors |

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| pgAdmin won't load at `:5050` | Wait 30s after first start; run `docker compose -f docker-compose.data.yml --profile tools up -d pgadmin` |
| Can't connect using `localhost` in pgAdmin | Use container names `timescaledb-vitals` / `postgres-clinical` on port `5432` |
| Qdrant collection empty | Re-run loader with `LOAD_NOTES=true` (see `IMPLEMENTATION.md` §5) |
| SQL tables empty | Ensure Docker stores are up, `.env` is loaded, then run `load_patients.py` |
| Wrong patient UUID | Re-read `infra/synthea/demo_patient_aliases.json` (regenerated each loader run) |

---

## PRD note

Browsing data in pgAdmin or the Qdrant dashboard is **developer verification only**.
Person B integrates via **MCP APIs**, not these UIs. Using them does not add work
to Person A's sprint plan or change Person B's frontend/agent deliverables.
