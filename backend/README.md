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

## Progress

- [x] **Phase 0** — repo bootstrap, `.env.example`, `requirements.txt`, uv 3.12 venv
- [x] **Phase 1 (Thu Jun 25)** — 3 data stores up + schemas verified; `connector_base.py` ABC
- [ ] **Phase 2 (Fri Jun 26)** — Synthea loader, populate vitals/labs/meds
- [ ] **Phase 3 (Fri Jun 26)** — Day-1 stub server + handoff to Person B
