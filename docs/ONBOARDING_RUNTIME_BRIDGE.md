# Onboarding Agent ↔ Runtime Agent — Bridge & Recent Updates

This document describes the **connections wired between build-time (onboarding) and
runtime (LangGraph agent)**, what was recently implemented, and how to test the full
pipeline end to end.

Companion docs:

- [`ONBOARDING_AGENT.md`](ONBOARDING_AGENT.md) — onboarding pipeline stages
- [`backend/onboarding_agent/README_CLI_TESTING.md`](../backend/onboarding_agent/README_CLI_TESTING.md) — interactive CLI walkthrough
- [`HANDOVER_PERSON_B.md`](HANDOVER_PERSON_B.md) — frozen MCP contracts
- [`PERSON_B_FRONTEND.md`](PERSON_B_FRONTEND.md) — pending frontend (chat + dashboard)

---

## Summary — what the bridge does

Before this work, the onboarding agent only wrote a `blueprint.yaml` and stopped. The
runtime agent used **hardcoded URLs** for the four original domains. There was no path
for a newly onboarded domain to appear in live clinical questions without editing
`agent/runtime_agent.py` by hand.

The bridge closes that gap in **three steps**:

| Step | Module | What it does |
| --- | --- | --- |
| **1. Generate** | `backend/onboarding_agent/generate.py` | Blueprint → runnable `backend/servers/<domain>/` package (main, tools stub, Dockerfile) |
| **2. Register** | `backend/onboarding_agent/register.py` | Blueprint → `registry-api POST /servers` → `registry-db` (URL, RBAC, tools) |
| **3. Discover** | `agent/runtime_agent.py` | When `REGISTRY_DISCOVERY=true`, agent reads `GET /servers` instead of static URLs |

```
Build-time                              Control plane                    Runtime
──────────                              ─────────────                    ───────

onboarding_agent/main.py
  discover → suggest → RBAC → approve
         │
         ▼
  blueprint.yaml ──► generate.py ──► backend/servers/<domain>/
         │                                    │
         │                                    │ uv run python …/main.py  (:8005)
         ▼                                    ▼
  register.py ──────────────► registry-api :8600 ──► registry-db
         POST /servers              GET /servers ◄──────── runtime_agent.py
         (tools + rbac)              (url + allowed_roles)   discover_servers()
                                                              REGISTRY_DISCOVERY=true
                                                                    │
                                                                    ▼
                                                              POST /ask  → MCP tools
```

---

## Connection 1 — `generate.py` (blueprint → server)

**File:** `backend/onboarding_agent/generate.py`

Instantiates the hardened template from an approved blueprint:

- `main.py` — Fixed Core (`FixedCoreGuard`), MCP tools, scope, Kong route metadata
- `tools.py` — **scaffold** (`SELECT * FROM <table> WHERE patient_id` + generic FHIR wrap)
- `Dockerfile`, `requirements.txt`, `blueprint.yaml` copy

```bash
uv run python -m backend.onboarding_agent.generate \
  backend/onboarding_agent/output/radiology_reports.blueprint.yaml
```

Output lands in `backend/servers/radiology_reports/` (demo domain).

**Important:** generated `tools.py` is intentionally generic — developers specialize SQL and
FHIR shaping for production. Plumbing (auth, audit, egress, cache) is fully generated.

---

## Connection 2 — `register.py` (blueprint → registry-db)

**File:** `backend/onboarding_agent/register.py`

Posts the blueprint to the control plane so the runtime can discover it:

```bash
# One domain
uv run python -m backend.onboarding_agent.register \
  backend/servers/radiology_reports/blueprint.yaml

# All committed server blueprints
uv run python -m backend.onboarding_agent.register --all

# Health sweep → health_checks table (for dashboard)
REGISTRY_DB_URL=postgresql://registry_user:registry_pass@localhost:5435/registry \
  uv run python -m backend.onboarding_agent.register --health
```

**Payload written to registry-api:**

| Field | Source |
| --- | --- |
| `server_name` / `domain` | `blueprint.yaml` |
| `kong_route` | `blueprint.yaml` |
| `port` | `DOMAIN_PORT` map in `register.py` |
| `scope` | `blueprint.yaml` |
| `tools` | tool names from blueprint |
| `rbac` | `{role: allow\|deny}` → `tool_specs` + `rbac_mappings` |

**Auth:** uses the **agent service identity** (`client_credentials` → Keycloak), not the
clinician token. This is an infra/control-plane call.

**Port map** (`DOMAIN_PORT` in `register.py`):

| Domain | Port |
| --- | --- |
| vitals_trends | 8001 |
| labs_diagnoses | 8002 |
| medications_interactions | 8003 |
| clinical_notes_search | 8004 |
| radiology_reports | 8005 |

Add a new row here when onboarding a domain on a new port.

---

## Connection 3 — `discover_servers()` in runtime agent

**File:** `agent/runtime_agent.py`

When `REGISTRY_DISCOVERY=true`, the agent:

1. Mints a service token (`client_credentials`)
2. Calls `GET {REGISTRY_URL}/servers`
3. Builds `{domain: {url, allowed_roles}}` from each row
4. Uses that in `_build_server_config()` for RBAC-aware MCP client selection

**URL resolution** (`DISCOVERY_VIA` env):

| Value | URL built |
| --- | --- |
| `direct` (default) | `http://localhost:{port}/mcp` |
| `kong` | `{KONG_BASE}{kong_route}` |

**Fallback:** if registry is down or `REGISTRY_DISCOVERY=false`, falls back to static
`VITALS_MCP_URL` … `NOTES_MCP_URL` and the frozen §6.3 RBAC matrix.

**RBAC at runtime:** `_build_server_config()` only opens MCP clients for servers where
the caller's `groups[]` intersects `allowed_roles` from the registry — so a newly
registered domain is callable automatically for the roles its blueprint allows.

```python
# agent/runtime_agent.py — env vars
REGISTRY_DISCOVERY=false          # flip to true after register --all
REGISTRY_URL=http://localhost:8600
DISCOVERY_VIA=direct              # or kong for gateway path
KONG_BASE=http://localhost:8000
```

---

## End-to-end pipeline (new domain)

Example: `radiology_reports` (demo domain already in repo).

### Prerequisites

1. Docker data stack up: `docker compose -f docker-compose.data.yml up -d`
2. Platform stack up: `docker compose -f docker-compose.platform.yml up -d`
3. `radiology_reports` table exists in Postgres clinical DB
4. Domain registered in `backend/shared/egress_guard.py` (`_SQL_BACKENDS`)

### Commands (in order)

```bash
# ── Stage A: Onboarding (build-time) ─────────────────────────────────────
uv run python -m backend.onboarding_agent.main radiology_reports
# → approve → backend/onboarding_agent/output/radiology_reports.blueprint.yaml

# ── Stage B: Generate server ─────────────────────────────────────────────
uv run python -m backend.onboarding_agent.generate \
  backend/onboarding_agent/output/radiology_reports.blueprint.yaml
# → backend/servers/radiology_reports/

# ── Stage C: Start the new server ──────────────────────────────────────────
uv run python backend/servers/radiology_reports/main.py
# → http://localhost:8005/mcp

# ── Stage D: Register in control plane ─────────────────────────────────────
uv run python -m backend.onboarding_agent.register \
  backend/servers/radiology_reports/blueprint.yaml

# ── Stage E: Enable discovery on runtime agent ─────────────────────────────
# In .env:
#   REGISTRY_DISCOVERY=true
#   DISCOVERY_VIA=direct

uv run uvicorn agent.runtime_agent:app --host 0.0.0.0 --port 8500

# ── Stage F: Ask a question (physician token) ──────────────────────────────
TOKEN=$(curl -s -X POST http://localhost:8080/realms/patient-risk/protocol/openid-connect/token \
  -d "client_id=patient-risk-agent" \
  -d "client_secret=agent-secret-change-in-prod" \
  -d "grant_type=client_credentials" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -X POST http://localhost:8500/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"Any radiology findings for demo-patient-1?","patient_id":"demo-patient-1","purpose_of_access":"routine_review"}'
```

### Still manual (known gaps)

| Gap | Who fixes | Notes |
| --- | --- | --- |
| Kong route in `infra/kong/kong.yml` | Person B / ops | Registry stores `kong_route`; Kong config is not auto-updated |
| `DOMAIN_PORT` entry | Developer | Add to `register.py` for each new domain |
| `egress_guard.py` backend | Developer | Required before onboarding can discover schema |
| Specialize `tools.py` | Developer | Scaffold queries are generic |
| Keycloak scope `mcp.radiology.read` | Person B | New domains need scope mappers in realm |

For dev/demo, `DISCOVERY_VIA=direct` works **without** a Kong route.

---

## Recent updates (what was implemented)

### Onboarding agent (build-time)

| Item | Status | Location |
| --- | --- | --- |
| Four-stage pipeline (discover → suggest → RBAC → assemble) | Done | `discover.py`, `suggest_tools.py`, `draft_rbac.py`, `assemble_blueprint.py` |
| Non-interactive orchestrator | Done | `run.py` |
| Interactive CLI with approve/modify/reject | Done | `main.py` |
| LLM tool suggestions + feedback loop | Done | `suggest_tools.py`, `main.py` option 1 |
| RBAC override + typo recovery | Done | `main.py` option 2, `draft_rbac.py` |
| New-domain FHIR heuristic + LLM metadata | Done | `discover.py`, `suggest_tools.py` |
| Golden-file RBAC tests (4 domains) | Done | `backend/tests/test_onboarding_agent.py` — **10 passed** |
| CLI testing guide | Done | `backend/onboarding_agent/README_CLI_TESTING.md` |
| Demo domain `radiology_reports` | Done | table + egress + blueprint + generated server |

### Factory + registry bridge (new)

| Item | Status | Location |
| --- | --- | --- |
| Server generator from blueprint | Done | `generate.py` |
| Registry registration script | Done | `register.py` |
| Health sweep → `health_checks` | Done | `register.py --health` |
| Registry stores tools + RBAC mappings | Done | `backend/registry/main.py` `POST /servers` |
| Registry returns `allowed_roles` per server | Done | `backend/registry/main.py` `GET /servers` |

### Runtime agent (consumer)

| Item | Status | Location |
| --- | --- | --- |
| Registry-driven server discovery | Done (opt-in) | `discover_servers()` in `runtime_agent.py` |
| Data-driven RBAC for MCP client selection | Done | `_build_server_config()` |
| Static fallback (4 domains) | Done | `_STATIC_URLS`, `_STATIC_RBAC` |
| `POST /ask` with purpose enum + alias resolution | Done | `runtime_agent.py` |
| LangGraph + MultiServerMCPClient fusion | Done | `_run_agent()` |

### Generated demo server

| Item | Status | Location |
| --- | --- | --- |
| `radiology_reports` MCP server | Generated | `backend/servers/radiology_reports/` |
| Port 8005, scope `mcp.radiology.read` | Configured | `main.py`, `blueprint.yaml` |
| 3 tools (scaffold SQL) | Generated | `tools.py` |

---

## Testing — what to run

### 1. Unit tests (no Docker, no LLM)

```bash
uv run pytest backend/tests/test_onboarding_agent.py -v
```

**Expected:** 10 passed — RBAC re-derives exactly match the four golden blueprints.

### 2. Interactive onboarding CLI

See full walkthrough: [`backend/onboarding_agent/README_CLI_TESTING.md`](../backend/onboarding_agent/README_CLI_TESTING.md)

Quick pass:

```bash
# Golden domain
uv run python -m backend.onboarding_agent.main vitals_trends
# → approve (0) → compare output to backend/servers/vitals_trends/blueprint.yaml

# New domain path
uv run python -m backend.onboarding_agent.main radiology_reports
# → test Modify Tools (1) and Modify RBAC (2) feedback loops
```

### 3. Generate + smoke the server

```bash
uv run python -m backend.onboarding_agent.generate \
  backend/onboarding_agent/output/radiology_reports.blueprint.yaml

uv run python backend/servers/radiology_reports/main.py &
curl -s http://localhost:8005/health | python3 -m json.tool
curl -s http://localhost:8005/usage  | python3 -m json.tool
```

### 4. Register + verify registry

```bash
# Platform must be up (registry-api :8600, keycloak :8080)
uv run python -m backend.onboarding_agent.register --all

TOKEN=$(curl -s -X POST http://localhost:8080/realms/patient-risk/protocol/openid-connect/token \
  -d "grant_type=client_credentials" \
  -d "client_id=patient-risk-agent" \
  -d "client_secret=agent-secret-change-in-prod" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s http://localhost:8600/servers \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

Confirm `radiology_reports` appears with `port: 8005`, `allowed_roles`, and `kong_route`.

### 5. Runtime discovery smoke

```bash
# Set in .env: REGISTRY_DISCOVERY=true
uv run python -c "
from agent.runtime_agent import discover_servers
import json
print(json.dumps({k: {**v, 'allowed_roles': sorted(v['allowed_roles'])} for k,v in discover_servers().items()}, indent=2))
"
```

With discovery on and radiology registered + running, output should include
`radiology_reports` alongside the original four domains.

### 6. Full `/ask` integration

Requires: MCP servers running, registry registered, `OPENAI_API_KEY` set,
`REGISTRY_DISCOVERY=true`.

```bash
uv run uvicorn agent.runtime_agent:app --host 0.0.0.0 --port 8500

curl -s -X POST http://localhost:8500/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is this patient overall risk picture?",
    "patient_id": "demo-patient-1",
    "purpose_of_access": "deterioration_review"
  }' | python3 -m json.tool
```

Check `servers_called` in the response — with discovery on, a 5th domain appears when
radiology is registered and the token's groups allow it.

### 7. Health sweep (dashboard data)

```bash
REGISTRY_DB_URL=postgresql://registry_user:registry_pass@localhost:5435/registry \
  uv run python -m backend.onboarding_agent.register --health
```

Writes rows to `health_checks` for the Tremor dashboard / registry health API.

---

## Environment variables (bridge-related)

Add to `.env` when testing the full pipeline:

```bash
# Registry discovery (runtime agent)
REGISTRY_DISCOVERY=true
REGISTRY_URL=http://localhost:8600
DISCOVERY_VIA=direct              # direct for host-run servers; kong for gateway path
KONG_BASE=http://localhost:8000

# Register script + audit persistence
REGISTRY_DB_URL=postgresql://registry_user:registry_pass@localhost:5435/registry
KEYCLOAK_ISSUER=http://localhost:8080/realms/patient-risk
KEYCLOAK_CLIENT_ID=patient-risk-agent
KEYCLOAK_CLIENT_SECRET=agent-secret-change-in-prod

# Agent synthesis
OPENAI_API_KEY=sk-...
```

Default in `.env.example`: `REGISTRY_DISCOVERY=false` (safe fallback to static 4-server config).

---

## Two auth identities (do not confuse)

| Caller | Token type | Used for |
| --- | --- | --- |
| **Clinician** (via frontend) | User JWT from Keycloak login | `POST /ask` → forwarded to MCP servers |
| **Agent service** | `client_credentials` | `register.py`, `discover_servers()` → registry-api |

The runtime agent uses **both**: service token to read the registry, user token to call MCP tools.

---

## Files touched by the bridge

```
backend/onboarding_agent/
├── generate.py          NEW — blueprint → server package
├── register.py          NEW — blueprint → registry-api
├── main.py              interactive approval CLI
├── run.py               non-interactive pipeline
├── discover.py          schema + FHIR heuristic
├── suggest_tools.py     LLM tool suggestions
├── draft_rbac.py        frozen matrix + new-domain defaults
└── assemble_blueprint.py

agent/
└── runtime_agent.py     discover_servers(), data-driven RBAC

backend/registry/
└── main.py              POST /servers stores tools+rbac; GET /servers returns allowed_roles

backend/shared/
└── egress_guard.py      radiology_reports backend added

backend/servers/radiology_reports/   GENERATED demo server
```

---

## Acceptance checklist (bridge "done")

- [ ] `pytest backend/tests/test_onboarding_agent.py` — 10/10 pass
- [ ] `main.py <domain>` → approved blueprint on disk
- [ ] `generate.py` → runnable server under `backend/servers/<domain>/`
- [ ] Server `/health` returns 200 on assigned port
- [ ] `register.py` → domain visible in `GET /servers`
- [ ] `REGISTRY_DISCOVERY=true` → `discover_servers()` includes new domain
- [ ] `POST /ask` → `servers_called` includes new domain (when RBAC allows)
- [ ] Audit rows land in `registry-db.audit_events` when `REGISTRY_DB_URL` set on MCP servers

---

## What's still Person B / later

| Item | Notes |
| --- | --- |
| Frontend chat/dashboard | See [`PERSON_B_FRONTEND.md`](PERSON_B_FRONTEND.md) |
| Auto Kong route provisioning | Manual `kong.yml` edit today |
| `ApprovalCard.tsx` web UI | CLI approval works; CopilotKit card is optional |
| Production-grade `tools.py` | Specialize generated scaffolds per domain |
| CI/CD wiring generate → register → deploy | Scripts exist; pipeline not automated yet |
