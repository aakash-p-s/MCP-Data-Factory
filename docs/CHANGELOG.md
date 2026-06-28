# Changelog

Notable changes to the Person A (data + backend) half, newest first. Commands that changed
for everyone are called out so Person B / other machines can stay in sync. See
[`PERSON_B_SYNC.md`](PERSON_B_SYNC.md) for the action checklist.

---

## 2026-06-28 — integration with Person B, real vitals server, determinism pin

### Synthea version pinned → `v4.0.0` (cross-machine determinism)
- **Why:** the download used `master-branch-latest`, a *moving* tag. Different download
  dates → different builds → different patients at the same seed (A/B datasets drifted).
- **Change:** `infra/synthea/load_patients.py` pins `SYNTHEA_VERSION = v4.0.0` and prints the
  jar build at generation time. Docs updated.
- **⚠ command change — re-download the jar:**
  ```bash
  rm -f infra/synthea/synthea-with-dependencies.jar
  curl -sL -o infra/synthea/synthea-with-dependencies.jar \
    https://github.com/synthetichealth/synthea/releases/download/v4.0.0/synthea-with-dependencies.jar
  ```
- **Data now:** 31 patients (`SYNTHEA_PATIENT_COUNT=31`, seed 42); `demo-patient-1 = 080b069b-5108-46b6-ecef-6aacd3b9ef3f`.
  Reseed reproducibility verified (identical patient + counts) with the pinned v4.0.0 jar.

### `vitals_trends` is now DB-backed (was a stub)
- `backend/connectors/sql_connector.py` — Connector ABC over asyncpg, read-only SELECT guard.
- `backend/servers/vitals_trends/news2.py` — published NHS NEWS2 algorithm.
- `backend/servers/vitals_trends/tools.py` — tools query live TimescaleDB, FHIR-shape rows.
- **Contract unchanged** (tool names, scope, route, FHIR shape, 403). Run command unchanged:
  ```bash
  uv run python backend/servers/vitals_trends/main.py     # -> http://localhost:8001/mcp
  ```

### Kong ↔ Keycloak JWT fixed (was `401 Invalid signature`)
- **Root cause:** placeholder RSA key in `kong.yml` + Keycloak regenerating its key on every
  re-init.
- **Fix:** pinned a **static RSA signing key** in `infra/keycloak/realm-export.json`
  (`rsa-static`, priority 200) with the matching public key in `infra/kong/kong.yml` (+ a
  cross-file note). Survives `down -v`.
- **⚠ command — re-init Keycloak once to pick up the static key:**
  ```bash
  docker compose -f docker-compose.platform.yml down
  docker volume rm data_factory_keycloak_data
  docker compose -f docker-compose.platform.yml up -d keycloak kong registry-db registry-api
  ```

### MCP server host-header fix (was `421 Invalid Host header` behind Kong)
- `backend/servers/vitals_trends/main.py` allow-lists Kong's forwarded Host
  (`host.docker.internal`) via MCP `TransportSecuritySettings` (DNS-rebind protection kept on).
- Extra hosts via `ALLOWED_HOSTS=host1,host2` env if needed.

### Green path verified end-to-end
Real Keycloak token → Kong (signature OK) → stub/real server → `get_vitals_trend` returns a
FHIR `Observation` (HTTP 200).

### Still open (not Person A code)
- Keycloak must issue tokens with `mcp.vitals.read` in the **`scp`** claim before Jul 2 RBAC
  (Person B — see [`PERSON_B_SYNC.md`](PERSON_B_SYNC.md) §5).

---

## 2026-06-26..28 — embeddings single source of truth
- `backend/shared/embeddings.py` owns the embedding model name, collection, and derived
  dimension; the loader and (Jul 6) `vector_connector.py` both import it, so the load-time and
  query-time models can never drift. `ensure_collection()` stamps the model into Qdrant;
  `assert_model_matches()` raises loudly on mismatch. (PRD §5.1.2 implemented as one module.)
- Clinical notes embedded into Qdrant (opt-in): `LOAD_NOTES=true uv run python infra/synthea/load_patients.py`.

## 2026-06-26 — Phases 0–3 (foundation)
- Data stores (`docker-compose.data.yml`): TimescaleDB :5433, Postgres :5434, Qdrant :6333.
- Schemas (`infra/postgres/*.sql`), connector ABC (`backend/shared/connector_base.py`).
- Synthea loader + `demo_patient_aliases.json` (fixed seed).
- Day-1 stub server for `vitals_trends` (hardcoded FHIR) — since replaced by the real server above.
