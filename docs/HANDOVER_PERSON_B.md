# Person B Handover — Stub Server & Platform Integration

Checklist for wiring Person B's platform (Keycloak, Kong, registry, runtime agent) to
Person A's **Day-1 `vitals_trends` stub**. Person A owns data stores + MCP servers;
Person B owns `docker-compose.platform.yml`, auth, gateway, registry, frontend, and agent.

For Person A setup, see [`IMPLEMENTATION.md`](IMPLEMENTATION.md). For architecture, see
[`README.md`](../README.md).

> **Before you build:** run the sync checklist in [`PERSON_B_SYNC.md`](PERSON_B_SYNC.md)
> (re-download Synthea v4.0.0, re-init Keycloak for the static key, add the `scp` scope
> mapping). See [`CHANGELOG.md`](CHANGELOG.md) for the exact command changes.

> **Branch:** clone and track **`person-a/phase-2`** — stub + data pipeline live there.
> **Formal compose merge:** Jul 8 (`docker-compose.data.yml` + `docker-compose.platform.yml`).

---

## 1. Fixed contract (do not change without same-day notice)

The stub contract is **frozen** in [`backend/servers/vitals_trends/blueprint.yaml`](../backend/servers/vitals_trends/blueprint.yaml).
Registry seeds for all four MCP servers should match these values even though only
`vitals_trends` is live today.

| Field | Value |
| --- | --- |
| Domain | `vitals_trends` |
| Direct MCP URL | `http://localhost:8001/mcp` |
| Kong route | `/mcp/clinical/vitals-trends/dev` |
| MCP path behind Kong | `/mcp` |
| Scope | `mcp.vitals.read` |
| Transport | Streamable HTTP |
| Success shape | FHIR R4 `Observation` JSON |
| Denial shape | `403 {"error":{"code":"forbidden","reason":"missing scope mcp.vitals.read"}}` |

**Tools (exact names):**

| Tool | Signature |
| --- | --- |
| `get_vitals_trend` | `(patient_id: str, hours: int = 24) -> list[Observation]` |
| `compute_news2_score` | `(patient_id: str) -> dict` |
| `list_abnormal_vitals` | `(patient_id: str, hours: int = 24) -> list[Observation]` |

**RBAC (vitals_trends):**

| Role | Access |
| --- | --- |
| `clinical-viewer` | Allow |
| `physician` | Allow |
| `case-manager` | Deny |

**MCP client headers (required for tool calls):**

```
Accept: application/json, text/event-stream
Content-Type: application/json
```

---

## 2. What Person A runs (prerequisite for integration)

Person B's Kong upstream must reach a host where Person A has started:

```bash
# Data stores (TimescaleDB, Postgres, Qdrant)
docker compose -f docker-compose.data.yml up -d

# Day-1 stub server
uv run python backend/servers/vitals_trends/main.py
```

Quick sanity checks:

```bash
curl -s http://localhost:8001/health          # JSON service summary (browser-friendly)
curl -s http://localhost:8001/mcp             # same summary if Accept lacks event-stream
```

Default ports: TimescaleDB **5433**, Postgres **5434**, Qdrant **6333**, stub **8001**.

---

## 3. Two integration modes

### Mode A — Direct stub (debugging, first wire-up)

Point the MCP client / agent at the stub **directly**:

```
http://localhost:8001/mcp
```

- **No bearer token required** on the stub (POC-friendly until Keycloak is fully wired).
- Use this to prove tool discovery + all three tool calls before Kong is in the path.

If Person B runs Kong/agent in Docker and the stub on the host:

| OS | Kong upstream host |
| --- | --- |
| Docker Desktop (Windows / macOS) | `host.docker.internal:8001` |
| Linux | host gateway IP or `172.17.0.1:8001` |

### Mode B — Full path (target runtime)

```
Clinician → Frontend → Runtime Agent → Kong → vitals_trends stub (port 8001)
```

- Kong (Layer 1): validate JWT, rate-limit, route to `/mcp/clinical/vitals-trends/dev`.
- Stub (Layer 2): when a **bearer token is present**, checks `scp` for `mcp.vitals.read`.
- Token **without** scope → stub returns the fixed `403` envelope above.
- Production agent config should use the **Kong URL**, not hardcoded `localhost:8001`.

---

## 4. JWT claims alignment

Person B's Keycloak realm (`patient-risk`) should issue tokens Person A's servers expect.

| Claim | Purpose |
| --- | --- |
| `sub` | User identity (audit) |
| `oid` | Object ID (Azure-style; keep if already validated) |
| `scp` | Space-delimited scopes — **must include `mcp.vitals.read`** for vitals tools |
| `groups` | Role mapping (`clinical-viewer`, `physician`, `case-manager`) |

`.env.example` on Person A's side already documents:

```
JWKS_URL=http://localhost:8080/realms/patient-risk/protocol/openid-connect/certs
JWT_AUDIENCE=patient-risk
```

**Stub vs production auth:**

| Behavior | Stub (now) | Production (Person A, Jul 2) |
| --- | --- | --- |
| No token | Allowed | Denied |
| Token, wrong/missing `scp` | `403` envelope | `403` envelope |
| JWT signature verify | Not enforced (decode only) | Full verify via `auth.py` |

---

## 5. Test patient IDs

Stub returns **hardcoded FHIR** (not DB-backed) until **Jun 29**. Any `patient_id`
string works for tool calls.

For demos aligned with Person A's synthetic SQL data, use friendly aliases from
[`infra/synthea/demo_patient_aliases.json`](../infra/synthea/demo_patient_aliases.json):

```bash
# Example: demo-patient-1 → UUID used in TimescaleDB / Postgres
python -c "import json; print(json.load(open('infra/synthea/demo_patient_aliases.json'))['demo-patient-1'])"
```

---

## 6. MCP SDK version

Pin the **`mcp` package identically** to Person A's [`requirements.txt`](../requirements.txt)
/ [`requirements.lock`](../requirements.lock). A version mismatch breaks Streamable HTTP
tool calls between agent and server.

---

## 7. Registry DB — seed validation

When seeding `mcp_servers` (four records), the **vitals_trends** row must match
`blueprint.yaml`:

- `kong_route` = `/mcp/clinical/vitals-trends/dev`
- `scope` = `mcp.vitals.read`
- `domain` = `vitals_trends`
- Upstream points at stub port **8001** until the real DB-backed server replaces it Jun 29

The other three servers (`labs_diagnoses`, `medications_interactions`,
`clinical_notes_search`) can be registered now but will **404 or fail upstream** until
Person A ships them (Jun 30 – Jul 6). That is expected.

---

## 8. Integration checklist (Person B)

Complete before calling stub integration "done":

- [ ] Cloned repo; on branch `person-a/phase-2`
- [ ] Person A data stack healthy (`docker-compose.data.yml ps`)
- [ ] Stub running; `curl http://localhost:8001/health` returns JSON summary
- [ ] MCP client calls all **3 tools** via **direct** `http://localhost:8001/mcp`
- [ ] Kong route `/mcp/clinical/vitals-trends/dev` proxies to stub upstream
- [ ] Physician / clinical-viewer token → vitals tool call **succeeds** via Kong
- [ ] case-manager token (or token missing `mcp.vitals.read`) → **403** with correct envelope
- [ ] Registry `mcp_servers` vitals row matches `blueprint.yaml`
- [ ] Agent runtime path uses Kong URL (not hardcoded localhost in final config)
- [ ] `mcp` SDK version matches Person A's lockfile

---

## 9. When Person A pulls Person B's platform config

| Milestone | What happens |
| --- | --- |
| **Now** | Person B pushes `docker-compose.platform.yml`, Kong config, Keycloak realm export, registry migrations/seeds to a `person-b/*` branch on the shared repo. Person A can merge that branch locally and run **both** compose files side by side. |
| **After stub-via-Kong works** | Joint smoke test on one machine (recommended). |
| **Jun 29** | Person A replaces stub with DB-backed `vitals_trends` — **same contract**, no agent/Kong URL changes. |
| **Jul 2** | Person A ships real JWT signature verification (`backend/shared/auth.py`). Person B retests token + scope denial. |
| **Jul 8** | **Formal merge:** `docker-compose.data.yml` + `docker-compose.platform.yml` → unified `docker-compose.yml`. |

### Person A — pull platform config locally

```bash
git fetch origin
git checkout person-a/phase-2
git merge origin/person-b/platform    # adjust branch name to Person B's push
```

Extend `.env` with Kong / Keycloak / registry variables (start from `.env.example` +
Person B's `.env.example` additions). Run:

```bash
docker compose -f docker-compose.data.yml up -d
docker compose -f docker-compose.platform.yml up -d
uv run python backend/servers/vitals_trends/main.py
```

Do **not** collapse into a single `docker-compose.yml` until Jul 8 unless both agree
early — separate files avoid blocking each other's sprint work.

---

## 10. Ownership summary

| Person A | Person B |
| --- | --- |
| `docker-compose.data.yml` | `docker-compose.platform.yml` |
| TimescaleDB, Postgres, Qdrant | Kong, Keycloak |
| Synthea loader + synthetic data | Registry DB, frontend |
| 4 MCP servers (stub → real) | Runtime agent (LangGraph + MCP clients) |
| SQL + vector connectors | Onboarding agent (build-time) |
| Layer-2 auth hardening (Jul 2) | Layer-1 gateway JWT + rate limits |

---

## 11. One-line handoff message (copy/paste)

> Clone `person-a/phase-2`. Run `docker-compose.data.yml` + `uv run python backend/servers/vitals_trends/main.py`. Point Kong upstream for `/mcp/clinical/vitals-trends/dev` at `host.docker.internal:8001`. MCP endpoint is `/mcp` with `Accept: application/json, text/event-stream`. Contract is in `blueprint.yaml` — do not change tool names, scope, or route. Test with `demo-patient-1` from `demo_patient_aliases.json`. Stub returns hardcoded data until Jun 29. Push `docker-compose.platform.yml` to `person-b/*` when stub-via-Kong works; Person A merges platform config then, full compose merge on Jul 8.
