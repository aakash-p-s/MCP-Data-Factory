# Patient Risk Intelligence MCP Platform — Person A (Data & Backend)

Backend/data half of the Patient Risk Intelligence MCP Platform: the 4 MCP servers
(`vitals_trends`, `labs_diagnoses`, `medications_interactions`, `clinical_notes_search`),
the SQL + Vector connectors, the 3 data stores, the Synthea data pipeline, and Layer-2
authorization/hardening. See the PRDs in the repo root for full specs.

## Requirements

- **Python 3.12** (PRD Codebase §8 requires Python 3.12 or 3.13 — do not use 3.11)
- [uv](https://docs.astral.sh/uv/) (package/venv manager)
- Docker + Docker Compose (for TimescaleDB, Postgres, Qdrant)

## Environment Setup

### 1. Configure secrets

```bash
cp .env.example .env
# edit .env and fill in real passwords
```

`.env` is gitignored; `.env.example` is committed and documents every required variable.

> Embedding model (`EMBEDDING_MODEL`) MUST match exactly between the Synthea loader and
> `vector_connector.py` — a mismatch silently returns meaningless similarity results.

### 2. Create the Python environment with uv

```bash
# Create a 3.12 venv (uses installed cpython-3.12.x — no download)
uv venv --python 3.12

# Install pinned dependencies
uv pip install -r requirements.txt

# Optional: activate (uv run works without activating)
source .venv/bin/activate
```

### 3. Verify

```bash
uv run python --version          # -> Python 3.12.x
uv run python -c "import fastapi, mcp, qdrant_client, sentence_transformers, jwt, asyncpg, tenacity; print('all imports OK')"
```

### (Optional) Lock exact versions

The PRD requires the `mcp` SDK to be pinned identically across all servers + Person B's
agent. To freeze the full resolved dependency tree:

```bash
uv pip compile requirements.txt -o requirements.lock
uv pip sync requirements.lock
```

## Dependencies

Pinned in [`requirements.txt`](../requirements.txt):

| Package | Purpose |
| --- | --- |
| `fastapi==0.136.*` | Web framework (wraps the MCP SDK app) |
| `mcp>=1.27,<2` | MCP Python SDK — pin identical across all servers + agent |
| `psycopg[binary]`, `asyncpg` | Postgres / TimescaleDB drivers |
| `pydantic>=2` | Tool input validation / models |
| `qdrant-client` | Vector DB client (`clinical_notes_search`) |
| `sentence-transformers` | Embeddings (`all-MiniLM-L6-v2`) |
| `pyjwt` | JWT re-verification (Layer-2 RBAC) |
| `tenacity` | Retry logic (self-healing) |
| `uvicorn[standard]` | ASGI server to run the FastAPI/MCP apps |
| `pytest` | RBAC matrix + self-healing tests |

## Project Layout (Person A scope)

```
infra/
  synthea/      # load_patients.py, demo_patient_aliases.json
  postgres/     # init-*.sql schema files
backend/
  shared/       # connector_base.py, auth.py, audit.py, cache.py, egress_guard.py, ...
  connectors/   # sql_connector.py, vector_connector.py
  servers/      # vitals_trends/, labs_diagnoses/, medications_interactions/, clinical_notes_search/
  tests/        # test_rbac_matrix.py, test_self_healing.py
docker-compose.data.yml   # TimescaleDB, Postgres, Qdrant, synthea-loader (Person A's half)
```

## Data Stores

Person A's half lives in [`docker-compose.data.yml`](../docker-compose.data.yml)
(`restart: unless-stopped`, schemas auto-applied on first init, healthchecks).

```bash
docker compose -f docker-compose.data.yml up -d          # start the 3 stores
docker compose -f docker-compose.data.yml ps             # check status
docker compose -f docker-compose.data.yml --profile tools up -d pgadmin   # optional UI
```

| Service | Container | Host port | Notes |
| --- | --- | --- | --- |
| TimescaleDB (vitals) | `timescaledb-vitals` | **5433** | `vitals` hypertable |
| Postgres (labs + meds) | `postgres-clinical` | **5434** | `5432` was taken locally → moved to 5434 |
| Qdrant (notes) | `qdrant` | **6333** / 6334 | dashboard at http://localhost:6333/dashboard |
| pgAdmin (optional) | `pgadmin` | **5050** | `--profile tools` only |

Schemas (Codebase PRD §7) run **only on first init** (empty volume). After editing a
`.sql` file, re-apply with:

```bash
docker compose -f docker-compose.data.yml down -v        # drops volumes
docker compose -f docker-compose.data.yml up -d
```

Verify tables landed:

```bash
docker exec timescaledb-vitals psql -U postgres -d vitals -c "\dt"
docker exec postgres-clinical psql -U postgres -d clinical -c "\dt"
```

## Synthea Data Pipeline

[`infra/synthea/load_patients.py`](../infra/synthea/load_patients.py) generates synthetic
FHIR R4 patients with a **fixed `SYNTHEA_SEED`** and loads vitals/labs/meds into the stores
above. The 188 MB jar and the generated `output/` are gitignored (regenerated from the seed).

One-time: download the Synthea jar (~188 MB):

```bash
curl -sL -o infra/synthea/synthea-with-dependencies.jar \
  https://github.com/synthetichealth/synthea/releases/download/master-branch-latest/synthea-with-dependencies.jar
```

Run the loader (data stores must be up; ~2 min — generates + truncates + loads):

```bash
set -a; . ./.env; set +a                      # export VITALS_DB_URL, CLINICAL_DB_URL, SEED
uv run python infra/synthea/load_patients.py
```

The loader truncates first, so re-running with the same `SYNTHEA_SEED` is reproducible —
`demo-patient-1` maps to the same UUID every time (written to
[`infra/synthea/demo_patient_aliases.json`](../infra/synthea/demo_patient_aliases.json)).

Clinical notes → Qdrant are **deferred to Jul 6** and skipped by default. To embed them
(pulls the `all-MiniLM-L6-v2` model on first run, ~80 MB, downloads automatically):

```bash
LOAD_NOTES=true uv run python infra/synthea/load_patients.py     # macOS/Linux
# Windows PowerShell:  $env:LOAD_NOTES="true"; uv run python infra/synthea/load_patients.py
```

> **Embedding model — single source of truth.** The model name, collection, and dimension
> live in [`backend/shared/embeddings.py`](shared/embeddings.py), imported by *both* the
> loader and (Jul 6) `vector_connector.py`. This implements PRD §5.1.2's "loader and query
> must match" by making drift impossible rather than relying on two copies staying equal.
> `ensure_collection()` stamps the model into the Qdrant collection; `assert_model_matches()`
> raises loudly if a later query uses a different model. Notes need Synthea's
> `--exporter.clinical_note.export` (the loader sets it), which writes `output/notes/*.txt`.

Verify data landed:

```bash
docker exec timescaledb-vitals psql -U postgres -d vitals   -c "SELECT count(*) FROM vitals;"
docker exec postgres-clinical  psql -U postgres -d clinical -c "SELECT count(*) FROM labs;"
python3 -c "import json; print(json.load(open('infra/synthea/demo_patient_aliases.json'))['demo-patient-1'])"
```

## Progress

- [x] **Phase 0** — repo bootstrap, `.env.example`, `requirements.txt`, uv 3.12 venv
- [x] **Phase 1 (Thu Jun 25)** — 3 data stores up + schemas verified; `connector_base.py` ABC
- [x] **Phase 2 (Fri Jun 26)** — Synthea loader; vitals=292, labs=6787, diagnoses=732, meds=1071; determinism verified
- [x] **Phase 3 (Fri Jun 26)** — Day-1 stub server (`vitals_trends`) verified + handed to Person B
- [ ] **Mon Jun 29** — real `vitals_trends` server: `sql_connector.py`, `tools.py`, `news2.py`

### Day-1 Stub Server (`backend/servers/vitals_trends/`)

MCP server over Streamable HTTP with hardcoded FHIR — unblocks Person B before the real
DB-backed server (Jun 29). Contract is **fixed** (see `blueprint.yaml`).

```bash
uv run python backend/servers/vitals_trends/main.py     # -> http://localhost:8001/mcp
```

| Field | Value |
| --- | --- |
| MCP endpoint | `http://localhost:8001/mcp` |
| Kong route | `/mcp/clinical/vitals-trends/dev` |
| Tools | `get_vitals_trend`, `compute_news2_score`, `list_abnormal_vitals` |
| Scope | `mcp.vitals.read` |
| Success | FHIR R4 `Observation` |
| Denial | `403 {"error":{"code":"forbidden","reason":"missing scope mcp.vitals.read"}}` |

A bearer token missing the scope gets the 403 envelope; no token is allowed (POC-friendly
until Keycloak is wired). Signature verification + full RBAC land Jul 2.
