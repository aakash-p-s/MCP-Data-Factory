# Quick Test — Run Commands

Step-by-step commands for the onboarding pipeline, factory bridge, runtime agent, and verification.
Run everything from the project root:

```bash
cd /Users/bhavnarathi/Desktop/Data_Factory
```

Companion docs: [`ONBOARDING_AGENT.md`](ONBOARDING_AGENT.md) · [`ONBOARDING_RUNTIME_BRIDGE.md`](ONBOARDING_RUNTIME_BRIDGE.md) · [`backend/onboarding_agent/README_CLI_TESTING.md`](../backend/onboarding_agent/README_CLI_TESTING.md)

**Registry discovery end-to-end:** see **§7** · env template: [`.env.example`](../.env.example)

---

## Domain reference (all examples below)

| Domain | Port | Scope | Storage | Sample `/ask` question |
| --- | --- | --- | --- | --- |
| `vitals_trends` | 8001 | `mcp.vitals.read` | TimescaleDB | *What are demo-patient-1 vitals over the last 24 hours?* |
| `labs_diagnoses` | 8002 | `mcp.labs.read` | Postgres | *What are the active diagnoses for demo-patient-1?* |
| `medications_interactions` | 8003 | `mcp.meds.read` | Postgres | *What medications is demo-patient-1 on and any interactions?* |
| `clinical_notes_search` | 8004 | `mcp.notes.read` | Qdrant | *Find recent clinical notes for demo-patient-1.* |
| `radiology_reports` | 8005 | `mcp.radiology.read` | Postgres | *Any radiology findings for demo-patient-1?* |

**Golden domains** (4 built-in): `vitals_trends`, `labs_diagnoses`, `medications_interactions`, `clinical_notes_search` — servers already exist under `backend/servers/`.

**New domain** (factory demo): `radiology_reports` — onboard → generate → register.

Demo patient alias: `demo-patient-1` (resolves to a Synthea UUID automatically).

**Valid `purpose_of_access` values** (typos like `medication_review` are auto-fixed):

`deterioration_review` · `medication_reconciliation` · `discharge_planning` · `care_coordination` · `routine_review`

**Recommended token for `/ask` examples** (physician — full access to all 4 core domains):

```bash
TOKEN=$(curl -s -X POST http://localhost:8080/realms/patient-risk/protocol/openid-connect/token \
  -d "grant_type=password" \
  -d "client_id=patient-risk-agent" \
  -d "client_secret=agent-secret-change-in-prod" \
  -d "username=doctor-test" \
  -d "password=test123" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
```

Nurse token (vitals + labs only — meds/notes/radiology excluded with clear `/ask` message):

```bash
NURSE_TOKEN=$(curl -s -X POST http://localhost:8080/realms/patient-risk/protocol/openid-connect/token \
  -d "grant_type=password" \
  -d "client_id=patient-risk-agent" \
  -d "client_secret=agent-secret-change-in-prod" \
  -d "username=nurse-test" \
  -d "password=test123" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

---

## 0. One-time setup (do this first)

```bash
# 1. Copy env file and set passwords + OPENAI_API_KEY
cp .env.example .env

# 2. Python environment
uv venv --python 3.12
uv pip install -r requirements.txt

# 3. Start Docker (data + platform: Keycloak, Kong, registry, DBs)
docker compose up -d
docker compose ps    # wait until data stores show "healthy"

# 4. Load env vars into your shell
set -a && source .env && set +a

# 5. Download Synthea jar (first time only)
curl -sL -o infra/synthea/synthea-with-dependencies.jar \
  https://github.com/synthetichealth/synthea/releases/download/v4.0.0/synthea-with-dependencies.jar
```

Then run **§0a Seed data** (or the seed steps inside **§6** walkthroughs) before onboarding.

---

## 0a. Seed data per MCP domain (tables + rows)

Each domain needs its **schema** (tables/collection) and **rows** before onboarding or starting its MCP server.

| Domain | Port | Tables / collection | Schema (auto on fresh `docker compose up`) | Seed this domain |
| --- | --- | --- | --- | --- |
| `vitals_trends` | 8001 | `vitals` | `init-timescale-vitals.sql` | §0a-A below |
| `labs_diagnoses` | 8002 | `labs`, `diagnoses` | `init-labs-diagnoses.sql` | §0a-A below |
| `medications_interactions` | 8003 | `medications`, `interaction_rules` | `init-medications.sql` + `seed-interaction-rules.sql` | §0a-A below |
| `clinical_notes_search` | 8004 | Qdrant `clinical_notes` | *(empty until seeded)* | §0a-B below |
| `radiology_reports` | 8005 | `radiology_reports` | `init-radiology.sql` | §0a-C below |

### 0a-A — Seed `vitals_trends`, `labs_diagnoses`, `medications_interactions`

Shared Synthea loader (one command seeds all three SQL domains):

```bash
set -a && source .env && set +a
uv run python infra/synthea/load_patients.py
```

**Verify per domain:**

```bash
# vitals_trends (:8001) — TimescaleDB
docker exec timescaledb-vitals psql -U postgres -d vitals \
  -c "SELECT count(*) AS vitals_rows FROM vitals;"

# labs_diagnoses (:8002) — Postgres clinical
docker exec postgres-clinical psql -U postgres -d clinical \
  -c "SELECT count(*) AS labs FROM labs; SELECT count(*) AS diagnoses FROM diagnoses;"

# medications_interactions (:8003) — same Postgres DB
docker exec postgres-clinical psql -U postgres -d clinical \
  -c "SELECT count(*) AS meds FROM medications; SELECT count(*) AS rules FROM interaction_rules;"
```

### 0a-B — Seed `clinical_notes_search` only (`:8004`)

```bash
set -a && source .env && set +a
LOAD_NOTES=true uv run python infra/synthea/load_patients.py

curl -s http://localhost:6333/collections/clinical_notes | python3 -m json.tool
# expect points_count > 0
```

### 0a-C — Seed `radiology_reports` only (`:8005`)

Auto on **fresh** Docker volume. Re-apply if the volume existed before `init-radiology.sql` was added:

```bash
docker exec -i postgres-clinical psql -U postgres -d clinical \
  < infra/postgres/init-radiology.sql

docker exec postgres-clinical psql -U postgres -d clinical \
  -c "SELECT count(*) AS radiology_rows FROM radiology_reports;"
# expect 3 rows (includes demo-patient-1 UUID)
```

### Re-seed from scratch

```bash
docker compose down -v && docker compose up -d
# wait for healthy, then re-run 0a-A / 0a-B / 0a-C as needed
```

---

## 0b. Common pitfalls — fixed in code

These used to fail silently or confusingly; the repo now handles them as below.

### 1. Invalid `purpose_of_access` → aliases accepted

Canonical values: `deterioration_review`, `medication_reconciliation`, `discharge_planning`, `care_coordination`, `routine_review`.

Common typos are **auto-normalized** in `agent/runtime_agent.py`:

| You send | Normalized to |
| --- | --- |
| `medication_review` | `medication_reconciliation` |
| `meds_review` | `medication_reconciliation` |
| `med_review` | `medication_reconciliation` |

Anything else still returns **HTTP 422** with the valid list.

### 2. Golden blueprint `diff` → tools now match committed files

For the 4 frozen domains, `suggest_tools.py` **reuses** `backend/servers/<domain>/blueprint.yaml` on the first pass (no LLM drift). After `main.py` → approve, tool names should match:

```bash
diff backend/onboarding_agent/output/vitals_trends.blueprint.yaml \
     backend/servers/vitals_trends/blueprint.yaml
# expect no diff (RBAC + tools)
```

Revision loops (Modify Tools with feedback) still call the LLM.

### 3. Nurse token for meds / notes → clear RBAC message

`nurse-test` (`grp-clinical-viewer`) may only reach **vitals + labs**. Meds, notes, and radiology require **`doctor-test`** / `test123`.

If no servers are reachable, `/ask` now returns an explicit message listing excluded domains instead of a vague partial answer:

```bash
# Nurse — vitals/labs OK
curl -s -X POST http://localhost:8500/ask \
  -H "Authorization: Bearer $NURSE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"Summarize demo-patient-1 vitals and labs.","patient_id":"demo-patient-1","purpose_of_access":"routine_review"}'

# Nurse — meds question → excluded domains named in response
curl -s -X POST http://localhost:8500/ask \
  -H "Authorization: Bearer $NURSE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"What medications is demo-patient-1 on?","patient_id":"demo-patient-1","purpose_of_access":"medication_review"}'
# medication_review is accepted (alias → medication_reconciliation)
```

### 4. Radiology `:8005` → included in startup + static discovery

- `bash scripts/start_mcp_servers.sh` now starts **:8001–8005** (skips if `radiology_reports/main.py` missing).
- `init-radiology.sql` is mounted in `docker-compose.yml` (auto on fresh volumes).
- Runtime agent static fallback includes `radiology_reports` on `:8005` for **physician** tokens (no `REGISTRY_DISCOVERY` required for basic `/ask`).

Still required for radiology: seed rows (step 3) and physician token.

### 5. Terminal paste errors (from live runs)

| Symptom | Cause | Fix |
| --- | --- | --- |
| `[Errno 48] address already in use` on `:8002` | Server already running | `curl localhost:8002/health` — if OK, **skip** start; else `lsof -ti :8002 \| xargs kill` |
| `zsh: command not found: #` | Pasted markdown `# comment` lines | Only paste **bash commands**, not `# A3 — …` headers |
| `SyntaxError` in `python3 -c` / `sys.stss_token` | Typo or broken quotes in TOKEN line | Use single-quoted Python: `'…["access_token"])'` — see Walkthrough A5 |
| `/ask` → `"Partial answer only"` | Empty `$TOKEN` or non-physician token | Run `echo ${#TOKEN}` — must be > 100; use `doctor-test` / `test123` |

### Quick “will it work?” summary

| Domain / step | Works when… |
| --- | --- |
| `pytest test_onboarding_agent.py` | Always (no Docker) |
| `run.py` / `main.py` (4 golden) | Docker up + §0a-A seed + `OPENAI_API_KEY` |
| `main.py clinical_notes_search` | Also §0a-B (`LOAD_NOTES=true`) |
| `main.py radiology_reports` | Also §0a-C (`init-radiology.sql`) |
| MCP `:8001–8005` | Seeds + `bash scripts/start_mcp_servers.sh` |
| `/ask` radiology | §0a-C + `:8005` running + physician token |

---

## 1. Onboarding pipeline

The four modules (`discover.py`, `suggest_tools.py`, `draft_rbac.py`, `assemble_blueprint.py`) are library files — run them through **`run.py`** (non-interactive) or **`main.py`** (interactive approval).

### A. `run.py` — full pipeline, no approval prompt

Runs: discover → suggest tools → draft RBAC → write blueprint YAML.

```bash
uv run python -m backend.onboarding_agent.run vitals_trends
uv run python -m backend.onboarding_agent.run labs_diagnoses
uv run python -m backend.onboarding_agent.run medications_interactions
uv run python -m backend.onboarding_agent.run clinical_notes_search
uv run python -m backend.onboarding_agent.run radiology_reports

# Custom output directory (optional)
uv run python -m backend.onboarding_agent.run vitals_trends \
  --output-dir backend/onboarding_agent/output
```

Output: `backend/onboarding_agent/output/<domain>.blueprint.yaml`

### B. `main.py` — interactive CLI (approve / modify tools / modify RBAC)

```bash
uv run python -m backend.onboarding_agent.main vitals_trends
uv run python -m backend.onboarding_agent.main labs_diagnoses
uv run python -m backend.onboarding_agent.main medications_interactions
uv run python -m backend.onboarding_agent.main clinical_notes_search
uv run python -m backend.onboarding_agent.main radiology_reports
```

At the prompt:

| Key | Action |
| --- | --- |
| `0` | Approve |
| `1` | Modify Tools |
| `2` | Modify RBAC |
| `3` | Cancel |

Verify output (golden domains should match committed blueprints exactly):

```bash
diff backend/onboarding_agent/output/vitals_trends.blueprint.yaml \
     backend/servers/vitals_trends/blueprint.yaml

diff backend/onboarding_agent/output/labs_diagnoses.blueprint.yaml \
     backend/servers/labs_diagnoses/blueprint.yaml

diff backend/onboarding_agent/output/medications_interactions.blueprint.yaml \
     backend/servers/medications_interactions/blueprint.yaml

diff backend/onboarding_agent/output/clinical_notes_search.blueprint.yaml \
     backend/servers/clinical_notes_search/blueprint.yaml

cat backend/onboarding_agent/output/radiology_reports.blueprint.yaml
```

### C. Unit tests — RBAC golden files (no Docker, no LLM)

```bash
uv run pytest backend/tests/test_onboarding_agent.py -v
```

Expected: **14+ passed** (includes golden-tool tests)

---

## 2. Factory bridge (after blueprint is approved)

### D. `generate.py` — blueprint → MCP server package

Use after approving a blueprint. The 4 golden servers are already committed; **`generate.py` is mainly for new domains** like `radiology_reports`.

```bash
# Golden domains (regenerate scaffold — optional)
uv run python -m backend.onboarding_agent.generate \
  backend/onboarding_agent/output/vitals_trends.blueprint.yaml
uv run python -m backend.onboarding_agent.generate \
  backend/onboarding_agent/output/labs_diagnoses.blueprint.yaml
uv run python -m backend.onboarding_agent.generate \
  backend/onboarding_agent/output/medications_interactions.blueprint.yaml
uv run python -m backend.onboarding_agent.generate \
  backend/onboarding_agent/output/clinical_notes_search.blueprint.yaml

# New domain (factory demo)
uv run python -m backend.onboarding_agent.generate \
  backend/onboarding_agent/output/radiology_reports.blueprint.yaml
```

Output: `backend/servers/<domain>/` (`main.py`, `tools.py`, `Dockerfile`, etc.)

### E. Start MCP servers

All core servers at once (`:8001–8005`, including radiology when present):

```bash
bash scripts/start_mcp_servers.sh
```

Or one server at a time:

```bash
uv run python backend/servers/vitals_trends/main.py              # :8001
uv run python backend/servers/labs_diagnoses/main.py             # :8002
uv run python backend/servers/medications_interactions/main.py   # :8003
uv run python backend/servers/clinical_notes_search/main.py      # :8004
uv run python backend/servers/radiology_reports/main.py          # :8005
```

Smoke check (per domain — swap port):

```bash
curl -s http://localhost:8001/health | python3 -m json.tool   # vitals_trends
curl -s http://localhost:8002/health | python3 -m json.tool   # labs_diagnoses
curl -s http://localhost:8003/health | python3 -m json.tool   # medications_interactions
curl -s http://localhost:8004/health | python3 -m json.tool   # clinical_notes_search
curl -s http://localhost:8005/health | python3 -m json.tool   # radiology_reports

curl -s http://localhost:8001/usage  | python3 -m json.tool   # usage counters
```

### F. `register.py` — blueprint → registry-api → registry-db

Platform must be up (`registry-api` on `:8600`, Keycloak on `:8080`).

```bash
# Register one domain
uv run python -m backend.onboarding_agent.register \
  backend/servers/vitals_trends/blueprint.yaml
uv run python -m backend.onboarding_agent.register \
  backend/servers/labs_diagnoses/blueprint.yaml
uv run python -m backend.onboarding_agent.register \
  backend/servers/medications_interactions/blueprint.yaml
uv run python -m backend.onboarding_agent.register \
  backend/servers/clinical_notes_search/blueprint.yaml
uv run python -m backend.onboarding_agent.register \
  backend/servers/radiology_reports/blueprint.yaml

# Register all committed server blueprints (recommended)
uv run python -m backend.onboarding_agent.register --all

# Health sweep → writes to health_checks table
REGISTRY_DB_URL=postgresql://registry_user:registry_pass@localhost:5435/registry \
  uv run python -m backend.onboarding_agent.register --health
```

Verify registry (service token — for `GET /servers` only):

```bash
SVC_TOKEN=$(curl -s -X POST http://localhost:8080/realms/patient-risk/protocol/openid-connect/token \
  -d "grant_type=client_credentials" \
  -d "client_id=patient-risk-agent" \
  -d "client_secret=agent-secret-change-in-prod" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s http://localhost:8600/servers \
  -H "Authorization: Bearer $SVC_TOKEN" | python3 -m json.tool
```

For `/ask` examples below, use the **physician** `TOKEN` from the domain reference section.

---

## 3. Runtime agent

### G. Enable registry discovery in `.env`

Add or set in `.env` (see `.env.example` for the full block):

```bash
REGISTRY_DISCOVERY=true
REGISTRY_URL=http://localhost:8600
DISCOVERY_VIA=direct
KEYCLOAK_ISSUER=http://localhost:8080/realms/patient-risk
KEYCLOAK_CLIENT_ID=patient-risk-agent
KEYCLOAK_CLIENT_SECRET=agent-secret-change-in-prod

RADIOLOGY_MCP_URL=http://localhost:8005/mcp
```

Reload env and **restart** the runtime agent (it reads env at startup only):

```bash
set -a && source .env && set +a

lsof -ti :8500 | xargs kill 2>/dev/null || true
uv run uvicorn agent.runtime_agent:app --host 0.0.0.0 --port 8500
```

Prerequisite: all domains registered first:

```bash
uv run python -m backend.onboarding_agent.register --all
```

### H. Start runtime agent

```bash
uv pip install -r agent/requirements.txt
uv run uvicorn agent.runtime_agent:app --host 0.0.0.0 --port 8500
```

Test discovery (separate terminal — must show **5 domains** from registry):

```bash
set -a && source .env && set +a
uv run python -c "
from agent.runtime_agent import discover_servers, REGISTRY_DISCOVERY
import json
print('REGISTRY_DISCOVERY:', REGISTRY_DISCOVERY)
print('domains:', sorted(discover_servers().keys()))
print(json.dumps({k: v['url'] for k, v in discover_servers().items()}, indent=2))
"
```

Expected:

```
REGISTRY_DISCOVERY: True
domains: ['clinical_notes_search', 'labs_diagnoses', 'medications_interactions', 'radiology_reports', 'vitals_trends']
```

Ask a question (one example per domain):

```bash
# vitals_trends (:8001)
curl -s -X POST http://localhost:8500/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"What are demo-patient-1 vitals over the last 24 hours?","patient_id":"demo-patient-1","purpose_of_access":"deterioration_review"}' \
  | python3 -m json.tool

# labs_diagnoses (:8002)
curl -s -X POST http://localhost:8500/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"What are the active diagnoses for demo-patient-1?","patient_id":"demo-patient-1","purpose_of_access":"routine_review"}' \
  | python3 -m json.tool

# medications_interactions (:8003)
curl -s -X POST http://localhost:8500/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"What medications is demo-patient-1 on and are there any drug interactions?","patient_id":"demo-patient-1","purpose_of_access":"medication_reconciliation"}' \
  | python3 -m json.tool

# clinical_notes_search (:8004 — requires LOAD_NOTES=true seed)
curl -s -X POST http://localhost:8500/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"Find recent clinical notes for demo-patient-1.","patient_id":"demo-patient-1","purpose_of_access":"routine_review"}' \
  | python3 -m json.tool

# radiology_reports (:8005 — after onboard + generate + register)
curl -s -X POST http://localhost:8500/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"Any radiology findings for demo-patient-1?","patient_id":"demo-patient-1","purpose_of_access":"routine_review"}' \
  | python3 -m json.tool

# Multi-domain fusion (all servers running + REGISTRY_DISCOVERY=true)
curl -s -X POST http://localhost:8500/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is demo-patient-1 overall risk picture?","patient_id":"demo-patient-1","purpose_of_access":"deterioration_review"}' \
  | python3 -m json.tool
```

---

## 6. Two domain walkthroughs (seed → test)

Complete step-by-step for **one golden domain** and **one new factory domain**.
Assumes **§0** one-time setup is done (`docker compose up`, `.env`, Synthea jar).

---

### Walkthrough A — `labs_diagnoses` (golden domain, port `:8002`)

Postgres tables `labs` + `diagnoses`. Server already exists under `backend/servers/labs_diagnoses/`.

#### A1 — Seed this domain

```bash
cd /Users/bhavnarathi/Desktop/Data_Factory
set -a && source .env && set +a

# Shared loader — also seeds vitals + meds (required once per machine)
uv run python infra/synthea/load_patients.py
```

Verify **labs_diagnoses** data only:

```bash
docker exec postgres-clinical psql -U postgres -d clinical -c "\dt labs diagnoses"
docker exec postgres-clinical psql -U postgres -d clinical \
  -c "SELECT count(*) AS labs FROM labs; SELECT count(*) AS diagnoses FROM diagnoses;"
```

Expected: both tables exist; counts > 0.

#### A2 — Onboard + approve blueprint

```bash
uv run python -m backend.onboarding_agent.main labs_diagnoses
# At prompt type: 0
```

Verify blueprint matches committed golden file (tool names + RBAC — YAML comments/format may differ):

```bash
grep 'name:' backend/onboarding_agent/output/labs_diagnoses.blueprint.yaml
grep -A3 '^rbac:' backend/onboarding_agent/output/labs_diagnoses.blueprint.yaml
grep -A3 '^rbac:' backend/servers/labs_diagnoses/blueprint.yaml
# expect same 3 tool names and identical rbac block
```

#### A3 — Start MCP server (`:8002`)

If `:8002` is **already running** (from `start_mcp_servers.sh` or a prior run), skip the start command — just verify health:

```bash
curl -s http://localhost:8002/health | python3 -m json.tool
```

If health fails or port is stuck, free the port then start:

```bash
lsof -ti :8002 | xargs kill 2>/dev/null || true
uv run python backend/servers/labs_diagnoses/main.py
```

In a **second terminal** — usage smoke (optional):

```bash
curl -s http://localhost:8002/usage | python3 -m json.tool
```

> Do **not** paste markdown comment lines (lines starting with `#`) into the terminal — zsh may error with `command not found: #`.

#### A4 — Register in control plane

```bash
set -a && source .env && set +a
uv run python -m backend.onboarding_agent.register \
  backend/servers/labs_diagnoses/blueprint.yaml
```

#### A5 — Runtime `/ask` (labs question)

Terminal 1 — runtime agent (if not already running):

```bash
set -a && source .env && set +a
uv pip install -r agent/requirements.txt
uv run uvicorn agent.runtime_agent:app --host 0.0.0.0 --port 8500
```

Terminal 2 — physician token + ask (run **line by line**; verify token before `/ask`):

```bash
TOKEN=$(curl -s -X POST http://localhost:8080/realms/patient-risk/protocol/openid-connect/token \
  -d "grant_type=password" \
  -d "client_id=patient-risk-agent" \
  -d "client_secret=agent-secret-change-in-prod" \
  -d "username=doctor-test" \
  -d "password=test123" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

echo "TOKEN length: ${#TOKEN}"
test "${#TOKEN}" -gt 100 || echo "ERROR: TOKEN empty — fix the curl line above before /ask"
```

Then `/ask`:

```bash
curl -s -X POST http://localhost:8500/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"What are the active diagnoses for demo-patient-1?","patient_id":"demo-patient-1","purpose_of_access":"routine_review"}' \
  | python3 -m json.tool
```

Expected: real clinical answer citing `labs_diagnoses` — **not** `"Partial answer only"`.

If you see `"Partial answer only"` → `$TOKEN` was empty or wrong (typo in `python3 -c` line). Use **single quotes** around the Python snippet as shown above.

#### A6 — Unit test (no Docker)

```bash
uv run pytest backend/tests/test_onboarding_agent.py -k labs_diagnoses -v
```

---

### Walkthrough B — `radiology_reports` (new factory domain, port `:8005`)

Postgres table `radiology_reports`. Full path: seed → onboard → **generate** → start → register → `/ask`.

#### B1 — Seed this domain

```bash
cd /Users/bhavnarathi/Desktop/Data_Factory
set -a && source .env && set +a

# Create table + 3 demo rows (safe to re-run — script truncates first)
docker exec -i postgres-clinical psql -U postgres -d clinical \
  < infra/postgres/init-radiology.sql
```

Verify **radiology_reports** data only:

```bash
docker exec postgres-clinical psql -U postgres -d clinical -c "\dt radiology_reports"
docker exec postgres-clinical psql -U postgres -d clinical \
  -c "SELECT patient_id, modality, impression FROM radiology_reports LIMIT 3;"
```

Expected: 3 rows; one row for `demo-patient-1` UUID `080b069b-5108-46b6-ecef-6aacd3b9ef3f`.

#### B2 — Onboard + approve blueprint

```bash
uv run python -m backend.onboarding_agent.main radiology_reports
# At prompt type: 0
```

Verify output written:

```bash
cat backend/onboarding_agent/output/radiology_reports.blueprint.yaml
cat backend/onboarding_agent/output/radiology_reports.discovery.yaml
```

Expected: `fhir_resource: DiagnosticReport`, `storage: postgres` — not `unknown`.

#### B3 — Generate MCP server package

```bash
uv run python -m backend.onboarding_agent.generate \
  backend/onboarding_agent/output/radiology_reports.blueprint.yaml
```

Verify generated files:

```bash
ls backend/servers/radiology_reports/
# main.py  tools.py  blueprint.yaml  Dockerfile  requirements.txt
```

#### B4 — Start MCP server (`:8005`)

```bash
uv run python backend/servers/radiology_reports/main.py
```

New terminal — health smoke:

```bash
curl -s http://localhost:8005/health | python3 -m json.tool
curl -s http://localhost:8005/usage  | python3 -m json.tool
```

#### B5 — Register in control plane

```bash
set -a && source .env && set +a
uv run python -m backend.onboarding_agent.register \
  backend/servers/radiology_reports/blueprint.yaml
```

Optional — confirm in registry:

```bash
SVC_TOKEN=$(curl -s -X POST http://localhost:8080/realms/patient-risk/protocol/openid-connect/token \
  -d "grant_type=client_credentials" \
  -d "client_id=patient-risk-agent" \
  -d "client_secret=agent-secret-change-in-prod" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s http://localhost:8600/servers \
  -H "Authorization: Bearer $SVC_TOKEN" | python3 -m json.tool | grep -A2 radiology
```

#### B6 — Runtime `/ask` (radiology question)

Terminal 1 — runtime agent:

```bash
set -a && source .env && set +a
uv run uvicorn agent.runtime_agent:app --host 0.0.0.0 --port 8500
```

Terminal 2 — physician token + ask:

```bash
TOKEN=$(curl -s -X POST http://localhost:8080/realms/patient-risk/protocol/openid-connect/token \
  -d "grant_type=password" \
  -d "client_id=patient-risk-agent" \
  -d "client_secret=agent-secret-change-in-prod" \
  -d "username=doctor-test" \
  -d "password=test123" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -X POST http://localhost:8500/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"Any radiology findings for demo-patient-1?","patient_id":"demo-patient-1","purpose_of_access":"routine_review"}' \
  | python3 -m json.tool
```

Expected: answer mentions radiology/imaging; `servers_called` includes `radiology_reports`.

#### B7 — Quick checklist

| Step | Pass? |
| --- | --- |
| B1 seed — 3 rows in `radiology_reports` | |
| B2 onboard — blueprint on disk | |
| B3 generate — `backend/servers/radiology_reports/main.py` exists | |
| B4 health — `:8005/health` → 200 | |
| B5 register — visible in `GET /servers` | |
| B6 `/ask` — radiology cited in answer | |

---

### Other domains — seed + test (copy-paste)

Use **§6 Walkthrough A/B** as the template. Swap domain name, port, and seed block:

| Domain | Seed step | Onboard | Generate? | Port | Sample `/ask` |
| --- | --- | --- | --- | --- | --- |
| `vitals_trends` | §0a-A + verify `vitals` count | `main vitals_trends` | No (golden) | 8001 | *vitals last 24h* |
| `labs_diagnoses` | §0a-A + verify `labs`/`diagnoses` | `main labs_diagnoses` | No | 8002 | *active diagnoses* |
| `medications_interactions` | §0a-A + verify `medications` | `main medications_interactions` | No | 8003 | *drug interactions* |
| `clinical_notes_search` | §0a-A **then** §0a-B | `main clinical_notes_search` | No | 8004 | *recent notes* |
| `radiology_reports` | §0a-C | `main radiology_reports` | **Yes** `generate.py` | 8005 | *radiology findings* |

---

## 4. Full end-to-end flow — per domain (short form)

See **§6** for full seed-included walkthroughs. Short reference:

### 4a. Golden domains (quick smoke — servers already exist)

> **Prerequisite:** §0a step 1 (SQL seed); step 2 for `clinical_notes_search`.

Skip generate; onboard only to prove the pipeline matches committed blueprints.

```bash
# Example: vitals_trends (seed: §0a step 1)
uv run python -m backend.onboarding_agent.main vitals_trends    # → type 0
diff backend/onboarding_agent/output/vitals_trends.blueprint.yaml \
     backend/servers/vitals_trends/blueprint.yaml
uv run python backend/servers/vitals_trends/main.py             # :8001
uv run python -m backend.onboarding_agent.register \
  backend/servers/vitals_trends/blueprint.yaml

# Example: labs_diagnoses (seed: §0a step 1)
uv run python -m backend.onboarding_agent.main labs_diagnoses    # → type 0
uv run python backend/servers/labs_diagnoses/main.py            # :8002
uv run python -m backend.onboarding_agent.register \
  backend/servers/labs_diagnoses/blueprint.yaml

# Example: medications_interactions (seed: §0a step 1)
uv run python -m backend.onboarding_agent.main medications_interactions   # → type 0
uv run python backend/servers/medications_interactions/main.py  # :8003
uv run python -m backend.onboarding_agent.register \
  backend/servers/medications_interactions/blueprint.yaml

# Example: clinical_notes_search (seed: §0a step 2 — LOAD_NOTES=true)
uv run python -m backend.onboarding_agent.main clinical_notes_search   # → type 0
uv run python backend/servers/clinical_notes_search/main.py     # :8004
uv run python -m backend.onboarding_agent.register \
  backend/servers/clinical_notes_search/blueprint.yaml
```

Or register all four at once after servers are up:

```bash
bash scripts/start_mcp_servers.sh
uv run python -m backend.onboarding_agent.register --all
```

### 4b. New domain — `radiology_reports` (full factory path)

> **Prerequisite:** §0a step 3 (`init-radiology.sql`) before onboarding.

```bash
# Step 0 — Ensure table + rows exist
docker exec -i postgres-clinical psql -U postgres -d clinical \
  < infra/postgres/init-radiology.sql

# Step 1 — Onboard + approve
uv run python -m backend.onboarding_agent.main radiology_reports
# → type 0 to approve

# Step 2 — Generate server
uv run python -m backend.onboarding_agent.generate \
  backend/onboarding_agent/output/radiology_reports.blueprint.yaml

# Step 3 — Start server
uv run python backend/servers/radiology_reports/main.py         # :8005

# Step 4 — Register in control plane
uv run python -m backend.onboarding_agent.register \
  backend/servers/radiology_reports/blueprint.yaml

# Step 5 — Set REGISTRY_DISCOVERY=true in .env, then start runtime agent
set -a && source .env && set +a
uv run uvicorn agent.runtime_agent:app --host 0.0.0.0 --port 8500

# Step 6 — Ask via /ask (use $TOKEN from section F above)
curl -s -X POST http://localhost:8500/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"Any radiology findings for demo-patient-1?","patient_id":"demo-patient-1","purpose_of_access":"routine_review"}' \
  | python3 -m json.tool
```

---

## 7. End-to-end workflow with `REGISTRY_DISCOVERY=true`

Full bridge: **seed → onboard → register → discovery → `/ask`**.

```mermaid
flowchart LR
    SEED[Seed data] --> ONB[main.py approve]
    ONB --> REG[register --all]
    REG --> ENV[REGISTRY_DISCOVERY=true]
    ENV --> AG[runtime agent :8500]
    AG -->|GET /servers| RA[registry-api :8600]
    AG -->|Bearer JWT| MCP[MCP :8001-8005]
    MCP --> ASK[POST /ask answer]
```

### Step 1 — One-time `.env` (copy from `.env.example`)

```bash
cp .env.example .env
# fill OPENAI_API_KEY, then set:
REGISTRY_DISCOVERY=true
```

Full registry block in `.env`:

| Variable | Value | Purpose |
| --- | --- | --- |
| `REGISTRY_DISCOVERY` | `true` | Read servers from registry instead of static URLs |
| `REGISTRY_URL` | `http://localhost:8600` | Control-plane API |
| `DISCOVERY_VIA` | `direct` | Build URLs as `http://localhost:{port}/mcp` |
| `KEYCLOAK_ISSUER` | `http://localhost:8080/realms/patient-risk` | Service token for `discover_servers()` |
| `KEYCLOAK_CLIENT_ID` | `patient-risk-agent` | Same client as `register.py` |
| `KEYCLOAK_CLIENT_SECRET` | `agent-secret-change-in-prod` | From realm export |
| `RADIOLOGY_MCP_URL` | `http://localhost:8005/mcp` | Static fallback only; discovery uses registry port |

### Step 2 — Platform + seed (if not already done)

```bash
docker compose up -d
set -a && source .env && set +a
uv run python infra/synthea/load_patients.py
docker exec -i postgres-clinical psql -U postgres -d clinical < infra/postgres/init-radiology.sql
bash scripts/start_mcp_servers.sh
```

### Step 3 — Register all domains in control plane

```bash
uv run python -m backend.onboarding_agent.register --all

REGISTRY_DB_URL=postgresql://registry_user:registry_pass@localhost:5435/registry \
  uv run python -m backend.onboarding_agent.register --health
```

Expected health sweep: all **5** servers `healthy`.

Verify registry:

```bash
SVC_TOKEN=$(curl -s -X POST http://localhost:8080/realms/patient-risk/protocol/openid-connect/token \
  -d "grant_type=client_credentials" \
  -d "client_id=patient-risk-agent" \
  -d "client_secret=agent-secret-change-in-prod" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

curl -s http://localhost:8600/servers -H "Authorization: Bearer $SVC_TOKEN" | python3 -m json.tool
```

### Step 4 — Restart runtime agent with discovery on

```bash
set -a && source .env && set +a
lsof -ti :8500 | xargs kill 2>/dev/null || true
uv run uvicorn agent.runtime_agent:app --host 0.0.0.0 --port 8500
```

Verify agent health shows **5 servers**:

```bash
curl -s http://localhost:8500/health | python3 -m json.tool
```

### Step 5 — Physician token

```bash
TOKEN=$(curl -s -X POST http://localhost:8080/realms/patient-risk/protocol/openid-connect/token \
  -d "grant_type=password" \
  -d "client_id=patient-risk-agent" \
  -d "client_secret=agent-secret-change-in-prod" \
  -d "username=doctor-test" \
  -d "password=test123" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

echo "TOKEN length: ${#TOKEN}"
```

### Step 6 — `/ask` both walkthrough domains (registry path)

**labs_diagnoses** (golden):

```bash
curl -s -X POST http://localhost:8500/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"What are the active diagnoses for demo-patient-1?","patient_id":"demo-patient-1","purpose_of_access":"routine_review"}' \
  | python3 -m json.tool
```

Expected: diagnoses listed with `(labs_diagnoses)` citations; `servers_called` includes all 5 domains.

**radiology_reports** (factory):

```bash
curl -s -X POST http://localhost:8500/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"Any radiology findings for demo-patient-1?","patient_id":"demo-patient-1","purpose_of_access":"routine_review"}' \
  | python3 -m json.tool
```

Expected: CT/XR findings with `(radiology_reports)` or tool-name citations; `radiology_reports` in `servers_called`.

### Step 7 — Automated checks

```bash
uv run pytest backend/tests/test_onboarding_agent.py backend/tests/test_runtime_agent_helpers.py -v
uv run pytest backend/tests/ -q
```

### End-to-end checklist (registry discovery)

| Check | Command | Expected |
| --- | --- | --- |
| Discovery on | `echo $REGISTRY_DISCOVERY` | `true` |
| 5 domains from registry | `discover_servers()` python snippet in §3 H | 5 domain names |
| Registry populated | `GET /servers` | 5 rows, all `healthy` |
| Health sweep | `register --health` | 5/5 healthy |
| Labs `/ask` | Walkthrough A question | cites `labs_diagnoses` |
| Radiology `/ask` | Walkthrough B question | cites radiology data |
| Unit tests | `pytest backend/tests/ -q` | 95 passed |

> **Important:** Changing `REGISTRY_DISCOVERY` requires restarting `uvicorn` on `:8500`. MCP servers on `:8001–8005` can keep running.

---

## 8. Verification checklist

| What | Command | Expected |
| --- | --- | --- |
| SQL seed loaded | `docker exec timescaledb-vitals psql -U postgres -d vitals -c "SELECT count(*) FROM vitals;"` | count > 0 |
| Notes seed loaded | `curl -s http://localhost:6333/collections/clinical_notes` | `points_count` > 0 |
| Radiology seed loaded | `docker exec postgres-clinical psql -U postgres -d clinical -c "SELECT count(*) FROM radiology_reports;"` | count = 3 |
| RBAC + golden tools | `uv run pytest backend/tests/test_onboarding_agent.py -v` | 14+ passed |
| All backend tests | `uv run pytest backend/tests/ -q` | all pass |
| MCP servers live | `bash scripts/start_mcp_servers.sh --verify` | health + tool calls OK |
| MCP tools/list smoke | `uv run python scripts/mcp_inspector_smoke.py` | 4/4 servers |
| Radiology health | `curl -s http://localhost:8005/health` | 200 |
| Registry discovery | `discover_servers()` with `REGISTRY_DISCOVERY=true` | 5 domains |
| Register all | `uv run python -m backend.onboarding_agent.register --all` | 5 registered |
| Health sweep | `REGISTRY_DB_URL=... register --health` | 5/5 healthy |
| Full backend tests | `uv run pytest backend/tests/ -q` | 95 passed |

---

## Quick reference — what each file does

| File | How to run | Output |
| --- | --- | --- |
| `discover.py` | via `run.py` / `main.py` | schema in memory |
| `suggest_tools.py` | via `run.py` / `main.py` | tool list (LLM) |
| `draft_rbac.py` | via `run.py` / `main.py` | RBAC matrix |
| `assemble_blueprint.py` | via `run.py` / `main.py` | `*.blueprint.yaml` |
| `run.py` | `uv run python -m backend.onboarding_agent.run <domain>` | YAML, no prompt |
| `main.py` | `uv run python -m backend.onboarding_agent.main <domain>` | YAML + approval |
| `generate.py` | `uv run python -m backend.onboarding_agent.generate <path>` | `backend/servers/<domain>/` |
| `register.py` | `uv run python -m backend.onboarding_agent.register ...` | registry-db entry |
| `runtime_agent.py` | `uv run uvicorn agent.runtime_agent:app --port 8500` | `POST /ask` |

---

## Ports

| Service | Port |
| --- | --- |
| Kong proxy | 8000 |
| `vitals_trends` MCP | 8001 |
| `labs_diagnoses` MCP | 8002 |
| `medications_interactions` MCP | 8003 |
| `clinical_notes_search` MCP | 8004 |
| `radiology_reports` MCP | 8005 |
| Keycloak | 8080 |
| Registry API | 8600 |
| Runtime agent | 8500 |
| TimescaleDB | 5433 |
| Postgres (clinical) | 5434 |
| Registry DB | 5435 |
| Qdrant | 6333 |
