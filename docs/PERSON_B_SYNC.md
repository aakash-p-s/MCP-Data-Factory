# Person B — Sync Checklist (do this BEFORE building agents / frontend)

Person A pushed integration fixes + the real `vitals_trends` server + a Synthea version
pin. A few of these change data/auth on your side, so sync first or you'll build against
stale state. Companion docs: [`HANDOVER_PERSON_B.md`](HANDOVER_PERSON_B.md) (contract),
[`CHANGELOG.md`](CHANGELOG.md) (what changed + commands), [`IMPLEMENTATION.md`](IMPLEMENTATION.md) (setup).

Tick these top-to-bottom. Items marked **⚠ action** need you to actually do something.

## 1. Pull the latest
```bash
git checkout person-a/phase-2
git pull
```

## 2. ⚠ Re-download Synthea (determinism pin)
The jar source changed from the moving `master-branch-latest` to the pinned **`v4.0.0`**,
so everyone generates the *same* patients. Your old jar = different patients.
```bash
rm -f infra/synthea/synthea-with-dependencies.jar
curl -sL -o infra/synthea/synthea-with-dependencies.jar \
  https://github.com/synthetichealth/synthea/releases/download/v4.0.0/synthea-with-dependencies.jar
set -a; . ./.env; set +a
uv run python infra/synthea/load_patients.py
```
- **31 patients**, `demo-patient-1` is now **`00050ed6-69b8-5c1f-02a3-dc3813143187`**.
- Use aliases from [`infra/synthea/demo_patient_aliases.json`](../infra/synthea/demo_patient_aliases.json), not hardcoded UUIDs.

## 3. ⚠ Re-init the platform stack (static Keycloak key)
The realm now pins a **static RSA signing key** so Kong stops throwing `Invalid signature`.
Clear the old Keycloak volume once so it re-imports the realm with the static key:
```bash
docker compose -f docker-compose.platform.yml down
docker volume rm data_factory_keycloak_data    # name may differ; check `docker volume ls`
docker compose -f docker-compose.platform.yml up -d keycloak kong registry-db registry-api
```

## 4. Verify the green path works (token → Kong → vitals)
Person A runs the data stores + server; then:
```bash
docker compose -f docker-compose.data.yml up -d
uv run python backend/servers/vitals_trends/main.py        # now DB-backed, same contract

TOK=$(curl -s -X POST http://localhost:8080/realms/patient-risk/protocol/openid-connect/token \
  -d grant_type=client_credentials -d client_id=patient-risk-agent \
  -d client_secret=agent-secret-change-in-prod | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/mcp/clinical/vitals-trends/dev -X POST \
  -H "Authorization: Bearer $TOK" -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# expect 200 (was 401 Invalid signature before the fix)
```

## 5. ⚠ YOUR fix to do — Keycloak scope mapping (needed before Jul 2)
Right now the agent token passes Kong but carries **no `mcp.vitals.read` scope**. Today the
server allows it (no token + stub-style). On **Jul 2** Person A turns on real Layer-2 RBAC
(`backend/shared/auth.py`), which reads the **`scp`** claim. Without it, every authorized call → 403.

- Add a Keycloak **protocol mapper / client scopes** so issued tokens include
  `mcp.vitals.read mcp.labs.read mcp.meds.read mcp.notes.read` (per role) in a **`scp`** claim
  (Keycloak's default is `scope` — the contract §6.1 expects `scp`).
- Provide Person A **3 test tokens (one per role)** so the RBAC matrix tests can run against real tokens.

## 6. Know what's live vs stubbed on Person A's side
| Server | State | When real |
| --- | --- | --- |
| `vitals_trends` | **DB-backed (live)** | done |
| `labs_diagnoses` | not built | Jun 30 |
| `medications_interactions` | not built | Jul 1 |
| `clinical_notes_search` | not built (notes already embedded in Qdrant) | Jul 6 |

Registering all 4 in `registry-db` now is fine; the unbuilt 3 will 404 upstream until shipped — expected.

## 7. Contract — do NOT change without same-day notice (§6, see HANDOVER)
- Token claims: `sub`, `oid`, `groups[]`, `scp` (space-separated)
- vitals: tools `get_vitals_trend / compute_news2_score / list_abnormal_vitals`, scope `mcp.vitals.read`, route `/mcp/clinical/vitals-trends/dev`
- Success → FHIR R4 `Observation`; denial → `403 {"error":{"code":"forbidden","reason":"missing scope <scope>"}}`
- Pin the `mcp` SDK to match [`requirements.lock`](../requirements.lock) (`mcp==1.28.0`)

---

## Then start YOUR build tasks (Person B PRD / tracker)
- [ ] **Jun 29** — Onboarding Agent: discover → suggest tools → draft RBAC → assemble blueprint (against the live vitals server)
- [ ] **Jun 30** — Runtime Agent skeleton: Host + MCP Client, against vitals (Kong URL, not hardcoded localhost)
- [ ] **Jul 1–2** — integrate labs + meds as Person A ships them; fusion + citations
- [ ] **Jul 3** — CopilotKit chat + NextAuth login; OTel/Jaeger; CHECKPOINT
- [ ] **Jul 6** — 4th MCP client (clinical_notes_search) once shipped
- [ ] **Jul 8** — merge `docker-compose.platform.yml` + `docker-compose.data.yml`
