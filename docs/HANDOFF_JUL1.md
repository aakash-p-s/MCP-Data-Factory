# Handoff — Jul 1, 2026 (Person A → Person B)

> **Update (Jul 6, 2026):** Person B delivery is **complete**. Frontend (`/chat`, `/dashboard`),
> runtime agent, registry integration, and end-to-end QA are verified. See
> [`troubleshooting.md`](troubleshooting.md) and [`PERSON_B_FRONTEND.md`](PERSON_B_FRONTEND.md).

Short summary of what landed on **`person-a/phase-2`**, what was tested live, and what Person B
delivered after this handoff.

**Runbook:** [`QUICK_TEST.md`](QUICK_TEST.md) · **Frontend spec:** [`PERSON_B_FRONTEND.md`](PERSON_B_FRONTEND.md) · **Bridge detail:** [`ONBOARDING_RUNTIME_BRIDGE.md`](ONBOARDING_RUNTIME_BRIDGE.md)

---

## Git status

| Item | Detail |
| --- | --- |
| Branch | `person-a/phase-2` (pushed to `origin`) |
| Today's commits | `05edcc8` → `16af990` (+ this doc) |
| Uncommitted (local) | `infra/synthea/demo_patient_aliases.json` — optional; see below |
| Not in git | `.env` (gitignored) — set `REGISTRY_DISCOVERY=true` locally after `register --all` |

---

## Today's commits (pushed)

### `05edcc8` — docs: add QUICK_TEST guide

| File | What |
| --- | --- |
| `docs/QUICK_TEST.md` | New — setup, onboarding, MCP, registry, runtime commands |

### `16af990` — feat: registry discovery bridge, QUICK_TEST walkthroughs, and pitfall fixes

| File | What changed |
| --- | --- |
| `docs/QUICK_TEST.md` | Per-domain seeds, pitfalls, Walkthrough A/B, §7 registry E2E, §8 checklist |
| `.env.example` | `RADIOLOGY_MCP_URL`, `KEYCLOAK_ISSUER`, `KEYCLOAK_CLIENT_ID`, discovery comments |
| `agent/runtime_agent.py` | Radiology `:8005` static fallback; purpose aliases; RBAC error messages |
| `backend/onboarding_agent/suggest_tools.py` | Golden 4 domains reuse committed blueprint tools |
| `backend/tests/test_onboarding_agent.py` | Golden-tool tests |
| `backend/tests/test_runtime_agent_helpers.py` | New — purpose + discovery tests |
| `docker-compose.yml` / `docker-compose.data.yml` | Auto-mount `init-radiology.sql` |
| `scripts/start_mcp_servers.sh` | Starts `:8001–8005` |

---

## Prior commits on branch (context)

The factory bridge was built before today; today's work hardened and documented it.

| Commit | What |
| --- | --- |
| `42c2ebd` | `register.py` + `discover_servers()` in runtime agent |
| `eb2ef9a` | Host URLs + RBAC-from-registry |
| `11636ae` | JWT signature verify on MCP servers |
| `eab7f7a` | Per-role scopes + audit → registry-db |
| `4eda234` | Audience check, health_checks, Jaeger |
| `e3bab05` | `generate.py` — blueprint → server package |
| `ee84aa2` | `ONBOARDING_RUNTIME_BRIDGE.md`, `PERSON_B_FRONTEND.md` |
| `d0a8a4c` | README rewrite |

---

## Live testing (Jul 1)

| Test | Result |
| --- | --- |
| Walkthrough A — `labs_diagnoses` onboard + `/ask` | OK — diagnoses cited |
| Walkthrough B — `radiology_reports` onboard + `/ask` | OK — CT/XR cited |
| `register --all` | 5 domains registered |
| `register --health` | 5/5 healthy |
| `REGISTRY_DISCOVERY=true` + agent restart | `discover_servers()` → 5 domains |
| `pytest backend/tests/` | 95 passed |
| Onboarding + runtime helper tests | 18 passed |

---

## Local only (not pushed)

| Item | Notes |
| --- | --- |
| `.env` | Set `REGISTRY_DISCOVERY=true`, `KEYCLOAK_ISSUER`, etc. Copy block from `.env.example`. |
| `demo_patient_aliases.json` | Local Synthea re-run drift; `demo-patient-1` unchanged. Use repo file or re-seed with `SYNTHEA_SEED=42`. |

---

## Done — Person B should not rebuild

- Onboarding CLI (`main.py`), `generate.py`, `register.py`
- MCP servers `:8001–8005` (4 golden + `radiology_reports`)
- Registry-api, health sweep, runtime `POST /ask` + registry discovery
- [`QUICK_TEST.md`](QUICK_TEST.md) §6–§7 as the runbook

---

## Person B — completed (Jul 6, 2026)

### Frontend + platform integration

| # | Task | Status |
| --- | --- | --- |
| 1 | Sync checklist | Done — [`PERSON_B_SYNC.md`](PERSON_B_SYNC.md) |
| 2 | `frontend/` — Next.js + NextAuth + CopilotKit | Done |
| 3 | `/chat` → `POST :8500/ask` | Done |
| 4 | `/dashboard` → `GET :8600/servers` | Done |
| 5 | Anomaly panel → `GET :8600/audit` | Done |
| 6 | `docker compose --profile full` → frontend `:3000` | Done |

### Optional enhancements (not blocking)

| Task | Notes |
| --- | --- |
| Kong route for `radiology_reports` | Manual edit `infra/kong/kong.yml` when routing via Kong |
| Keycloak scope `mcp.radiology.read` | Only needed if MCP traffic goes via Kong |
| Web onboarding approval UI | CLI works; CopilotKit card is optional |
| CI/CD | Automate `generate` → `register` → deploy |

---

## Person B quick start

```bash
git checkout person-a/phase-2
cp .env.example .env    # OPENAI_API_KEY; REGISTRY_DISCOVERY=true after register
docker compose up -d
bash scripts/start_mcp_servers.sh
uv run python -m backend.onboarding_agent.register --all
set -a && source .env && set +a
uv run uvicorn agent.runtime_agent:app --host 0.0.0.0 --port 8500
```

Then follow [`QUICK_TEST.md`](QUICK_TEST.md) §6–§7.

---

## One-line summary

> Onboarding → generate → register → discovery → `/ask` → clinician UI is **complete** for 5
> domains. Full stack verified Jul 6, 2026 (see [`troubleshooting.md`](troubleshooting.md)).
