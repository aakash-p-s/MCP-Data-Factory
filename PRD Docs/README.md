# PRD — Product Requirements Documents

Primary reference for the **Patient Risk Intelligence MCP Platform**. Implementation
status for Person A is tracked in [`Person_A_Tasks.xlsx`](../Person_A_Tasks.xlsx) at the
repo root; living setup/contract docs are in [`docs/`](../docs/).

---

## Documents in this folder

| File | Audience | Contents |
| --- | --- | --- |
| [`Patient_Risk_Intelligence_PRD-1.pdf`](Patient_Risk_Intelligence_PRD-1.pdf) | Everyone | Master PRD — problem, architecture, workflow, acceptance |
| [`Patient_Risk_Intelligence_Complete_Codebase_PRD_v1.0.pdf`](Patient_Risk_Intelligence_Complete_Codebase_PRD_v1.0.pdf) | Engineers | Full codebase spec — §5 Fixed Core, §6 integration contract, §7 schemas, §8 stack |
| [`PersonA_Data_Backend_Engineer_PRD_v1.0.pdf`](PersonA_Data_Backend_Engineer_PRD_v1.0.pdf) | **Person A** | Data stores, Synthea, 4 MCP servers, connectors, hardening, tests |
| [`PersonB_Platform_Agent_Engineer_PRD_v1.0.pdf`](PersonB_Platform_Agent_Engineer_PRD_v1.0.pdf) | **Person B** | Kong, Keycloak, registry, runtime agent, frontend, onboarding agent |

---

## Person A — PRD scope vs repo (summary)

Aligned with **PersonA PRD** + **Codebase PRD §5–7** and [`Person_A_Tasks.xlsx`](../Person_A_Tasks.xlsx).

### Done

| PRD area | Deliverable |
| --- | --- |
| **Infra** | TimescaleDB `:5433`, Postgres `:5434`, Qdrant `:6333`; SQL init scripts; unified [`docker-compose.yml`](../docker-compose.yml) |
| **Data** | Synthea loader (pinned **v4.0.0**, seed 42, **31 patients**); `demo_patient_aliases.json`; optional notes → Qdrant (`LOAD_NOTES=true`) |
| **Connectors** | `SQLConnector`, `VectorConnector` — same `Connector` ABC |
| **4 MCP servers** | `vitals_trends` :8001 · `labs_diagnoses` :8002 · `medications_interactions` :8003 · `clinical_notes_search` :8004 (**12 tools**) |
| **Fixed Core** | `auth.py`, `audit.py` (+ `purpose_of_access` enum), `egress_guard.py`, `cache.py`, `FixedCoreGuard`, `self_healing.py` |
| **Embeddings** | Single source in `backend/shared/embeddings.py` + Qdrant fingerprint guard |
| **Tests** | `test_rbac_matrix.py` (auth engine), `test_rbac_matrix_http.py` (4×3 HTTP matrix), `test_mcp_inspector.py`, `test_fixed_core.py`, `test_self_healing.py`, `test_clinical_notes_search.py` — **62 pytest passing**; `scripts/mcp_inspector_smoke.py --in-process` (4/4 servers) |

### Partial / open

| PRD area | Gap |
| --- | --- |
| **Fixed Core (optional PRD)** | `telemetry.py`, `tool_trust.py`, `usage_log.py`, `fhir_shape.py` not shipped |
| **Jul 9 demo** | Final fixes + live demo support |

### Person B (not Person A)

Keycloak `scp`/`groups[]` mappers, runtime agent, frontend, onboarding agent — see
[`docs/HANDOVER_PERSON_B.md`](../docs/HANDOVER_PERSON_B.md).

---

## Quick links

- Setup: [`docs/IMPLEMENTATION.md`](../docs/IMPLEMENTATION.md)
- MCP servers: [`docs/MCP_SERVERS.md`](../docs/MCP_SERVERS.md)
- Integration contract: [`docs/HANDOVER_PERSON_B.md`](../docs/HANDOVER_PERSON_B.md)
- Changelog: [`docs/CHANGELOG.md`](../docs/CHANGELOG.md)
