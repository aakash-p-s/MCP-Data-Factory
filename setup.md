# Patient Risk Intelligence MCP Platform
## Setup Guide — Person B (Platform & Agent Engineer)

---

# SECTION 1 — First Time Setup
*Run these steps only once when setting up the project for the first time.*

---

## Step 1 — Prerequisites

Make sure these are installed before starting:

| Tool | Version | Check command |
|---|---|---|
| Docker Desktop | Latest | `docker --version` |
| Python | 3.12 | `python --version` |
| uv | Latest | `uv --version` |
| Java | 17 | `java -version` |

---

## Step 2 — Clone the repository

```bash
cd /c/Users/Aakash/Documents
git clone https://github.com/aakash-p-s/MCP-Data-Factory.git
cd MCP-Data-Factory
```

---

## Step 3 — Copy environment file

```bash
cp .env.example .env
```

Open `.env` in VS Code and fill in:
```
OPENAI_API_KEY=sk-your-real-key-here
```

Leave everything else as default.

---

## Step 4 — Create Python virtual environment

```bash
uv venv --python 3.12
```

Expected:
```
Using CPython 3.12.x
Creating virtual environment at: .venv
```

---

## Step 5 — Install dependencies

```bash
uv pip install -r requirements.txt
uv pip install -r agent/requirements.txt
```

---

## Step 6 — Verify all imports work

```bash
uv run python -c "import fastapi, mcp, qdrant_client, asyncpg, jwt; print('all imports OK')"
```

Expected:
```
all imports OK
```

---

## Step 7 — Start all Docker services

```bash
docker compose up -d
```

Wait 30 seconds then verify:

```bash
docker compose ps
```

Expected:
```
timescaledb-vitals    healthy
postgres-clinical     healthy
qdrant                running
keycloak              running
kong                  healthy
registry-db           healthy
registry-api          running
jaeger                running
```

---

## Step 8 — Download Synthea jar (188 MB — one time only)

```bash
curl.exe -k -L -o infra/synthea/synthea-with-dependencies.jar https://github.com/synthetichealth/synthea/releases/download/v4.0.0/synthea-with-dependencies.jar
```

Verify:
```bash
java -jar infra/synthea/synthea-with-dependencies.jar --help
```

---

## Step 9 — Load environment variables

```powershell
Get-Content .env | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
    $name, $value = $_ -split '=', 2
    [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim())
}
```

No output expected.

---

## Step 10 — Load Synthea patient data

```bash
uv run python infra/synthea/load_patients.py
```

Expected:
```
31 patients | vitals=456 labs=8261 diagnoses=1019 medications=1096
```

---

## Step 11 — Load clinical notes into Qdrant

```powershell
$env:LOAD_NOTES="true"
uv run python infra/synthea/load_patients.py
```

Verify:
```bash
curl.exe -s http://localhost:6333/collections/clinical_notes
```

Expected: `"points_count": 1617`

---

## Step 12 — Load drug interaction rules

```powershell
Get-Content infra/postgres/seed-interaction-rules.sql | docker exec -i postgres-clinical psql -U postgres -d clinical
```

Expected:
```
TRUNCATE TABLE
INSERT 0 6
```

---

## Step 13 — Create request files for testing

```powershell
'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | Out-File -Encoding utf8 request.json
```

```powershell
'{"question":"What is this patient overall risk picture?","patient_id":"demo-patient-1","purpose_of_access":"deterioration_review"}' | Out-File -Encoding utf8 ask.json
```

---

## Step 14 — Run the MCP Inspector smoke test

```bash
uv run python scripts/mcp_inspector_smoke.py
```

Expected:
```
[PASS] vitals_trends :8001 — ok
[PASS] labs_diagnoses :8002 — ok
[PASS] medications_interactions :8003 — ok
[PASS] clinical_notes_search :8004 — ok
4/4 servers passed
```

---

*First time setup is complete. From now on use Section 2 every time you open your laptop.*

---
---

# SECTION 2 — Daily Startup
*Run these steps every time you open your laptop.*

---

## Step 1 — Open Docker Desktop

Look for the whale icon in your taskbar. If not running, open Docker Desktop and wait until it says **"Docker Desktop is running."**

---

## Step 2 — Open VS Code

Open your project folder:
```
C:\Users\Aakash\Documents\MCP\MCP-Data-Factory
```

Press `` Ctrl + ` `` to open the terminal.

---

## Step 3 — Confirm you are in the right folder

```bash
pwd
```

Expected:
```
/c/Users/Aakash/Documents/MCP/MCP-Data-Factory
```

---

## Step 4 — Start all Docker services

```bash
docker compose up -d
```

Wait 30 seconds then verify:

```bash
docker compose ps
```

---

## Step 5 — Verify Keycloak is working

```bash
curl.exe -s http://localhost:8080/realms/patient-risk
```

Expected: JSON with `"realm": "patient-risk"`.
If connection refused — wait 15 more seconds and retry.

---

## Step 6 — Load environment variables

```powershell
Get-Content .env | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
    $name, $value = $_ -split '=', 2
    [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim())
}
```

---

## Step 7 — Start all 4 MCP servers

Open 4 separate terminals — press `` Ctrl + Shift + ` `` for each.

**Terminal 1:**
```bash
uv run python backend/servers/vitals_trends/main.py
```

**Terminal 2:**
```bash
uv run python backend/servers/labs_diagnoses/main.py
```

**Terminal 3:**
```bash
uv run python backend/servers/medications_interactions/main.py
```

**Terminal 4:**
```bash
uv run python backend/servers/clinical_notes_search/main.py
```

---

## Step 8 — Verify all 4 servers are healthy

Open a 5th terminal:

```bash
curl.exe -s http://localhost:8001/health
curl.exe -s http://localhost:8002/health
curl.exe -s http://localhost:8003/health
curl.exe -s http://localhost:8004/health
```

All should return JSON with `"status": "ok"`.

---

## Step 9 — Start the Runtime Agent

From the project root (not inside agent/ folder):

```bash
uv run uvicorn agent.runtime_agent:app --host 0.0.0.0 --port 8500
```

Verify in a new terminal:

```bash
curl.exe -s http://localhost:8500/health
```

Expected:
```json
{
  "status": "ok",
  "service": "runtime-agent",
  "demo_aliases_loaded": 31
}
```

---

## Step 10 — Quick system test

Get a token:

```powershell
$TOKEN = (curl.exe -s -X POST http://localhost:8080/realms/patient-risk/protocol/openid-connect/token -d "client_id=patient-risk-agent" -d "client_secret=agent-secret-change-in-prod" -d "username=doctor-test" -d "password=test123" -d "grant_type=password" -d "scope=openid" | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

Test the agent:

```powershell
curl.exe -s -X POST http://localhost:8500/ask -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -d "@ask.json"
```

If you get a JSON answer with citations — system is fully up and ready.

---

## Quick Reference — Services and Ports

| Service | URL | Port |
|---|---|---|
| Keycloak | http://localhost:8080 | 8080 |
| Kong proxy | http://localhost:8000 | 8000 |
| Kong admin | http://localhost:8101 | 8101 |
| Qdrant dashboard | http://localhost:6333/dashboard | 6333 |
| Jaeger UI | http://localhost:16686 | 16686 |
| registry-api | http://localhost:8600 | 8600 |
| vitals server | http://localhost:8001 | 8001 |
| labs server | http://localhost:8002 | 8002 |
| medications server | http://localhost:8003 | 8003 |
| notes server | http://localhost:8004 | 8004 |
| Runtime Agent | http://localhost:8500 | 8500 |

---

## Test Users

| Username | Password | Role | Can access |
|---|---|---|---|
| doctor-test | test123 | grp-physician | All 4 servers |
| nurse-test | test123 | grp-clinical-viewer | Vitals + Labs only |
| casemanager-test | test123 | grp-case-manager | Clinical notes only |

---

## Demo Patient

| Field | Value |
|---|---|
| Alias | demo-patient-1 |
| UUID | 080b069b-5108-46b6-ecef-6aacd3b9ef3f |
| Name | Chester802 Aufderhar910 |
| NEWS2 score | 1 (low risk) |
| Drug interaction | Lisinopril + Naproxen (moderate) |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Keycloak internal server error | `docker compose down -v` then `docker compose up -d` |
| Token expired | Get a fresh token and retry — tokens expire after 5 minutes |
| Agent shows wrong OpenAI key | Run agent from project root, not from inside agent/ folder |
| clinical_notes missing in Qdrant | Run `$env:LOAD_NOTES="true"` then `uv run python infra/synthea/load_patients.py` |
| Interaction rules show 0 rows | Run `Get-Content infra/postgres/seed-interaction-rules.sql \| docker exec -i postgres-clinical psql -U postgres -d clinical` |
| MCP server port conflict | Kong admin is on 8101 — MCP servers use 8001-8004 |
| `No module named prompts` | Run uvicorn from project root not from inside agent/ folder |
