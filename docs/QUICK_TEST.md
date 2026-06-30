# Quick Test — Run Commands

Step-by-step commands for the onboarding pipeline, factory bridge, runtime agent, and verification.
Run everything from the project root:

```bash
cd /Users/bhavnarathi/Desktop/Data_Factory
```

Companion docs: [`ONBOARDING_AGENT.md`](ONBOARDING_AGENT.md) · [`ONBOARDING_RUNTIME_BRIDGE.md`](ONBOARDING_RUNTIME_BRIDGE.md) · [`backend/onboarding_agent/README_CLI_TESTING.md`](../backend/onboarding_agent/README_CLI_TESTING.md)

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

# 4. Load env vars into your shell
set -a && source .env && set +a

# 5. Download Synthea jar (first time only)
curl -sL -o infra/synthea/synthea-with-dependencies.jar \
  https://github.com/synthetichealth/synthea/releases/download/v4.0.0/synthea-with-dependencies.jar

# 6. Seed synthetic patient data
uv run python infra/synthea/load_patients.py

# 7. (Optional) Load clinical notes into Qdrant for :8004
LOAD_NOTES=true uv run python infra/synthea/load_patients.py
```

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

Verify output:

```bash
cat backend/onboarding_agent/output/vitals_trends.blueprint.yaml
```

### C. Unit tests — RBAC golden files (no Docker, no LLM)

```bash
uv run pytest backend/tests/test_onboarding_agent.py -v
```

Expected: **10 passed**

---

## 2. Factory bridge (after blueprint is approved)

### D. `generate.py` — blueprint → MCP server package

```bash
uv run python -m backend.onboarding_agent.generate \
  backend/onboarding_agent/output/radiology_reports.blueprint.yaml
```

Output: `backend/servers/radiology_reports/` (`main.py`, `tools.py`, `Dockerfile`, etc.)

### E. Start MCP servers

All 4 core servers at once:

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

Smoke check:

```bash
curl -s http://localhost:8005/health | python3 -m json.tool
curl -s http://localhost:8005/usage  | python3 -m json.tool
```

### F. `register.py` — blueprint → registry-api → registry-db

Platform must be up (`registry-api` on `:8600`, Keycloak on `:8080`).

```bash
# Register one domain
uv run python -m backend.onboarding_agent.register \
  backend/servers/radiology_reports/blueprint.yaml

# Register all committed server blueprints
uv run python -m backend.onboarding_agent.register --all

# Health sweep → writes to health_checks table
REGISTRY_DB_URL=postgresql://registry_user:registry_pass@localhost:5435/registry \
  uv run python -m backend.onboarding_agent.register --health
```

Verify registry:

```bash
TOKEN=$(curl -s -X POST http://localhost:8080/realms/patient-risk/protocol/openid-connect/token \
  -d "grant_type=client_credentials" \
  -d "client_id=patient-risk-agent" \
  -d "client_secret=agent-secret-change-in-prod" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s http://localhost:8600/servers \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

---

## 3. Runtime agent

### G. Enable discovery in `.env`

```bash
REGISTRY_DISCOVERY=true
REGISTRY_URL=http://localhost:8600
DISCOVERY_VIA=direct
```

Reload env:

```bash
set -a && source .env && set +a
```

### H. Start runtime agent

```bash
uv pip install -r agent/requirements.txt
uv run uvicorn agent.runtime_agent:app --host 0.0.0.0 --port 8500
```

Test discovery (separate terminal):

```bash
uv run python -c "
from agent.runtime_agent import discover_servers
import json
print(json.dumps(discover_servers(), indent=2))
"
```

Ask a question:

```bash
curl -s -X POST http://localhost:8500/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Any radiology findings for demo-patient-1?",
    "patient_id": "demo-patient-1",
    "purpose_of_access": "routine_review"
  }' | python3 -m json.tool
```

---

## 4. Full end-to-end flow (new domain example)

```bash
# Step 1 — Onboard + approve
uv run python -m backend.onboarding_agent.main radiology_reports
# → type 0 to approve

# Step 2 — Generate server
uv run python -m backend.onboarding_agent.generate \
  backend/onboarding_agent/output/radiology_reports.blueprint.yaml

# Step 3 — Start server
uv run python backend/servers/radiology_reports/main.py

# Step 4 — Register in control plane
uv run python -m backend.onboarding_agent.register \
  backend/servers/radiology_reports/blueprint.yaml

# Step 5 — Set REGISTRY_DISCOVERY=true in .env, then start runtime agent
set -a && source .env && set +a
uv run uvicorn agent.runtime_agent:app --host 0.0.0.0 --port 8500

# Step 6 — Ask via /ask (use $TOKEN from register section above)
curl -s -X POST http://localhost:8500/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"Any radiology findings for demo-patient-1?","patient_id":"demo-patient-1","purpose_of_access":"routine_review"}'
```

---

## 5. Verification checklist

| What | Command | Expected |
| --- | --- | --- |
| RBAC unit tests | `uv run pytest backend/tests/test_onboarding_agent.py -v` | 10 passed |
| All backend tests | `uv run pytest backend/tests/ -q` | all pass |
| MCP servers live | `bash scripts/start_mcp_servers.sh --verify` | health + tool calls OK |
| MCP tools/list smoke | `uv run python scripts/mcp_inspector_smoke.py` | 4/4 servers |

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
| MCP servers | 8001–8005 |
| Keycloak | 8080 |
| Registry API | 8600 |
| Runtime agent | 8500 |
| TimescaleDB | 5433 |
| Postgres (clinical) | 5434 |
| Registry DB | 5435 |
| Qdrant | 6333 |
