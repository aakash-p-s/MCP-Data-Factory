# Onboarding Agent — Build Guide (for Person B)

The **onboarding agent** (`backend/onboarding_agent/`) is a **build-time** process, run once
per new domain. It discovers a source's schema, suggests an MCP tool set, drafts RBAC, and
writes a `blueprint.yaml` — its **only output**. It never deploys anything; a human approves
the YAML, then the existing hardened template (Person A's `backend/servers/*`) generates the
server. **Not built yet — this is Person B's deliverable.**

Companion: [`MCP_SERVERS.md`](MCP_SERVERS.md) (how a server is built),
[`HANDOVER_PERSON_B.md`](HANDOVER_PERSON_B.md) (the frozen contract).

```
pick a domain → discover schema → suggest tools (LLM) → draft RBAC → write blueprint.yaml → human approves
```

---

## The 4 files to build (PRD §5.5)

| File | Function | Responsibility |
| --- | --- | --- |
| `discover.py` | `discover_schema(connector) -> dict` | introspect the source via Person A's `Connector.schema()` |
| `suggest_tools.py` | `suggest_tools(schema) -> list[dict]` | one LLM call: schema → draft `{name, description}` tool pairs |
| `draft_rbac.py` | `draft_rbac(tools, role_matrix) -> dict` | apply the fixed RBAC matrix → per-tool scopes |
| `assemble_blueprint.py` | `assemble_blueprint(domain, schema, tools, rbac) -> Path` | write `blueprint.yaml` (the approval artifact) |

---

## Discovery — reuse Person A's connectors (the key handoff)

Discovery needs no new DB code. Call the `Connector` ABC Person A built, via the egress guard
(which hands back a connector already bound to that domain's backend):

```python
from backend.shared.egress_guard import locked_connector_for

conn = locked_connector_for("vitals_trends")   # or labs_diagnoses / medications_interactions / clinical_notes_search
await conn.connect()
schema = await conn.schema()
```

Return shapes:
- **SQLConnector.schema()** → `{ "<table>": [ {"column": ..., "type": ...}, ... ] }` (from `information_schema`)
- **VectorConnector.schema()** → `{ vector_size, metadata field names }` (the Qdrant collection shape)

---

## Target output — `blueprint.yaml`

Person A's **4 existing blueprints are the canonical examples** (`backend/servers/<domain>/blueprint.yaml`).
`assemble_blueprint.py` must emit this exact shape so the generated server's contract stays
consistent. Use them as **golden-file fixtures**: for a known domain, `suggest_tools` +
`draft_rbac` should reproduce the committed blueprint.

```yaml
domain: vitals_trends
storage: timescaledb
fhir_resource: Observation
terminology: LOINC
scope: mcp.vitals.read
kong_route: /mcp/clinical/vitals-trends/dev
mcp_endpoint: /mcp
tools:
  - name: get_vitals_trend
    signature: "(patient_id: str, hours: int = 24) -> list[Observation]"
  - name: compute_news2_score
    signature: "(patient_id: str) -> dict"
  - name: list_abnormal_vitals
    signature: "(patient_id: str, hours: int = 24) -> list[Observation]"
rbac: { clinical-viewer: allow, physician: allow, case-manager: deny }
denial_envelope: '{"error":{"code":"forbidden","reason":"missing scope mcp.vitals.read"}}'
```

---

## RBAC matrix that `draft_rbac.py` applies (PRD §6.3)

| Role | vitals | labs | meds | notes |
| --- | :--: | :--: | :--: | :--: |
| clinical-viewer | allow | allow | deny | deny |
| physician | allow | allow | allow | allow |
| case-manager | deny | deny | deny | allow |

---

## Per-domain reference (so suggested tools/scopes match the frozen contract)

| Domain | Connector | Scope | FHIR | Tools |
| --- | --- | --- | --- | --- |
| vitals_trends | SQL (Timescale) | `mcp.vitals.read` | Observation | get_vitals_trend, compute_news2_score, list_abnormal_vitals |
| labs_diagnoses | SQL (Postgres) | `mcp.labs.read` | Observation, Condition | get_lab_trend, get_active_diagnoses, get_diagnosis_history |
| medications_interactions | SQL (Postgres) | `mcp.meds.read` | MedicationStatement | get_active_medications, check_drug_interactions, get_polypharmacy_risk |
| clinical_notes_search | Vector (Qdrant) | `mcp.notes.read` | DocumentReference | semantic_search_notes, get_recent_notes, get_notes_by_type |

---

## Practical tips

- **Golden-file tests:** the 4 committed blueprints are the validation oracle — re-deriving one
  for a known domain proves `suggest_tools` + `draft_rbac` work.
- **LLM:** reuse the `gpt-4o` + `OPENAI_API_KEY` setup already in `agent/runtime_agent.py`.
- **Side-effect-free:** output one YAML to a path; the human/CI reviews before the template
  generates the server. The agent never touches Kong, the registry, or the DBs (beyond read-only
  `schema()` introspection).
- **Ownership:** this lives in Person B's scope, but is built *on top of* Person A's `Connector`
  ABC, `egress_guard.locked_connector_for`, and the 4 blueprints — mostly wiring discovery → LLM → YAML.
