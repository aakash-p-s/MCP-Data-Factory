# Troubleshooting Log — Person B QA Pass (Jul 3, 2026)

Record of bugs found and fixed during an end-to-end verification pass of the frontend +
runtime agent + registry against the backend Person A already shipped. Each entry is
**symptom → root cause → fix → how it was verified**, in the order found.

Companion docs: [`PERSON_B_FRONTEND.md`](PERSON_B_FRONTEND.md) (frontend spec) ·
[`QUICK_TEST.md`](QUICK_TEST.md) (setup/run commands) ·
[`HANDOVER_PERSON_B.md`](HANDOVER_PERSON_B.md) (frozen contracts)

---

## Summary table

| # | Issue | Files | Status |
|---|---|---|---|
| 1 | `server_name` never recorded in audit trail | `backend/shared/{request_context,middleware,audit}.py` | ✅ Fixed |
| 2 | Jaeger trace_id didn't match audit trace_id | `backend/shared/telemetry.py` | ✅ Fixed |
| 3 | No single shared trace per clinical question | `agent/runtime_agent.py` | ✅ Fixed |
| 4 | Denied (401/403) requests had no Jaeger span at all | `backend/shared/middleware.py` | ✅ Fixed |
| 5 | Agent crashed with `GraphRecursionError` → 503 | `agent/runtime_agent.py` | ✅ Fixed |
| 6 | `purpose_of_access` silently lost before reaching audit | `agent/runtime_agent.py` | ✅ Fixed |
| 7 | Agent connected to every RBAC-permitted server regardless of question relevance | `backend/onboarding_agent/register.py`, `backend/registry/main.py`, `agent/runtime_agent.py` | ✅ Fixed |
| 7b | `NameError` inside the lazy-tool closure (found while fixing #7) | `agent/runtime_agent.py` | ✅ Fixed |
| 8 | Physicians saw a false "restricted access" warning (regression from #7) | `agent/runtime_agent.py`, `frontend/components/AnswerBubble.tsx`, `frontend/app/chat/page.tsx` | ✅ Fixed |
| 9 | Dashboard "Status" badge never live-checked server health | `backend/registry/main.py`, `docker-compose.yml` | ✅ Fixed |
| 10 | "Registry API" / "Kong Gateway" sidebar lights are hardcoded green | `frontend/app/chat/page.tsx` | ⚠️ **Open — not fixed** |

---

## 1. `server_name` never recorded in the audit trail

**Symptom:** every row in `audit_events` had `server_name = NULL`, even though the column
exists and the frontend's anomaly panel (`AnomalyPanel.tsx`) depends on it for the
**Cross-role Probing** heuristic (groups denials by distinct server).

**Root cause:** `audit_phi()` in [`backend/shared/audit.py`](../backend/shared/audit.py)
called `log_call(...)` without ever forwarding `server_name`, and the direct `log_call(...)`
calls inside [`backend/shared/middleware.py`](../backend/shared/middleware.py) (the `:auth`
events) had the same gap.

**Fix:**
- Added a `service` field to `RequestContext` / `set_context()` in
  [`backend/shared/request_context.py`](../backend/shared/request_context.py).
- `middleware.py` now passes `server_name=self.service` on every `log_call()` site.
- `audit_phi()` reads `ctx.service` and forwards it.

**Verified:** fresh audit rows all carry the correct `server_name`; replayed the
`AnomalyPanel.tsx` Cross-role Probing logic in Python against live data and confirmed it
now fires correctly.

---

## 2. Jaeger trace_id didn't match the audit trace_id

**Symptom:** clicking a trace-ID link from the dashboard (`/trace/{trace_id}`) always 404'd.

**Root cause:** `telemetry.span()` opened a normal OTel span (SDK mints its own random trace
ID) and only stored the real correlation ID as a span *attribute* (`app.trace_id`) — never
as the actual trace context.

**Fix:** `_parent_context()` in
[`backend/shared/telemetry.py`](../backend/shared/telemetry.py) builds a remote-parent
`SpanContext` from the given trace_id before opening the span, so the real OTel trace ID
now equals the audit trace_id.

**Verified:** `GET /api/traces/{trace_id}` resolves directly with `errors: null`.

---

## 3. No single shared trace per clinical question

**Symptom:** multiple MCP calls belonging to the *same* `/ask` request each got a
different, unrelated `trace_id`.

**Root cause:** `agent/runtime_agent.py` never sent a `traceparent` header to the MCP
servers it calls, and never called `telemetry.configure()` itself — it wasn't even a
registered Jaeger service.

**Fix:** the agent now mints one `trace_id` per `/ask` call, sends it as a `traceparent`
header via `_build_server_config()`, calls `telemetry.configure("runtime_agent")` at
startup, and wraps the whole request in a root span.

**Verified:** one `/ask` call now produces 40 spans across all 6 services (agent + 5 MCP
servers) under a single Jaeger trace ID.

---

## 4. Denied (401/403) requests had no Jaeger span at all

**Symptom:** a trace_id from a *denial* audit row (403) still 404'd in Jaeger even after
fix #2/#3 — found while manually verifying a trace-ID link the user clicked.

**Root cause:** in `middleware.py`, only the two *allowed* code paths opened a
`telemetry.span(...)`. All four deny branches (tool-trust failure, missing bearer, invalid
JWT, RBAC denial) called `log_call()` and returned directly — no span, ever.

**Fix:** wrapped all 4 deny branches in `with telemetry.span(f"{self.service}.denied", ...)`.

**Verified:** re-triggered the same denials; all 3 fresh 403 trace_ids resolved in Jaeger
with a real span.

---

## 5. Agent crashed with `GraphRecursionError` → 503

**Symptom:** `Error: Recursion limit of 15 reached without hitting a stop condition.`

**Root cause:** `SYNTHESIS_PROMPT` in [`agent/prompts.py`](../agent/prompts.py) is a static
system prompt that always claims "You have access to 4 data sources," regardless of which
servers RBAC actually filtered into the toolset for that specific request. A restricted
role (e.g. clinical-viewer) asked about an excluded domain had no tool for it but didn't
know that was expected — it kept hunting with whatever tools it did have until it blew the
step budget.

**Fix (in `agent/runtime_agent.py`):**
- `full_question` now explicitly lists which domains are available/excluded for this
  specific request.
- `recursion_limit` bumped 15 → 25 as a safety margin.
- Added a dedicated `except GraphRecursionError` branch that returns a graceful degraded
  message instead of a 503.

**Verified:** reproduced the exact original scenario (200 now, clean "not accessible"
answer), stress-tested 4 more restricted-role/excluded-domain combinations, re-ran the full
regression suite.

---

## 6. `purpose_of_access` silently lost before reaching audit

**Symptom:** the dashboard's "Questions by Purpose" chart always showed "routine review
(100%)" no matter what a clinician actually picked in the UI.

**Root cause:** the agent never sent the `X-Purpose-Of-Access` header to the MCP servers,
so `middleware.py`'s `normalize_purpose(headers.get("x-purpose-of-access"))` always fell
back to the default.

**Fix:** added the header in `_build_server_config()`.

**Verified:** a `medication_reconciliation`-purpose question that called vitals tools now
correctly shows up as a real Purpose Mismatch anomaly (previously silent).

---

## 7. Agent connected to every RBAC-permitted server regardless of question relevance

**Symptom:** asking "What is this patient's current heart rate?" (needs only
`vitals_trends`) generated **20 audit events across all 5 servers** — 4 of them completely
unused for the answer. `servers_called` in the response also listed all 5, which was
misleading.

**Root cause:** `_run_agent()` eagerly opened an MCP session (auth handshake + RBAC check +
audit write) with *every* RBAC-permitted server just to ask each one "what tools do you
have?" — before the LLM even saw the question.

**Fix (3 files):**
- `backend/onboarding_agent/register.py` — parses each tool's `signature` string from
  `blueprint.yaml` into a real JSON Schema (`signature_to_schema()`) and sends it at
  registration time.
- `backend/registry/main.py` — `POST /servers` now stores that schema in the
  previously-always-empty `tool_specs` table; new `GET /servers/{id}/tools` endpoint serves
  it back.
- `agent/runtime_agent.py` — builds the LLM's tools from these *cached* schemas (no live
  connection needed for discovery); each tool's execution function only opens a real MCP
  connection **the moment the LLM actually invokes it**. A domain never invoked is never
  touched.

**Verified:** the same heart-rate question now generates only 8 audit events, all in
`vitals_trends`; `servers_called` correctly shows `["vitals_trends"]`. Broad
"overall risk picture" questions still correctly touch all 5 servers (no under-connection).

### 7b. `NameError: MultiServerMCPClient` inside the new lazy-tool closure

**Symptom:** after the fix above, the same heart-rate question started returning "No data
available" with `servers_called: []` — silently wrong, not an error.

**Root cause:** `MultiServerMCPClient` was imported *locally* inside `_run_agent()`. The new
`_build_lazy_tool()` / its inner `_call()` are module-level functions — Python closures
capture variables lexically based on where a function is *defined*, not where it's called
from, so `_call()` couldn't see `_run_agent`'s local import. The resulting `NameError` was
silently absorbed by LangGraph's tool-error handling and surfaced to the LLM as a vague
"no data" tool result instead of a crash.

**Fix:** re-import `MultiServerMCPClient` inside `_call()` itself.

**Verified:** isolated unit test of the lazy tool → real FHIR `Observation` data returned;
full regression suite re-run clean.

---

## 8. Physicians saw a false "restricted access" warning (regression from #7)

**Symptom:** logged in as `doctor-test` (physician, full access), asked a radiology-only
question, and the answer bubble showed *"You have access to 1 of 5 servers. Physician role
required for full access."*

**Root cause:** `frontend/components/AnswerBubble.tsx` computed "servers you don't have
access to" as `ALL_SERVERS - servers_called`. That accidentally worked before fix #7,
because `servers_called` used to list every RBAC-permitted server regardless of relevance.
After #7 made `servers_called` reflect only servers *actually used*, the frontend had no way
to tell "not needed for this question" apart from "not accessible for your role."

**Fix:**
- Added a new `servers_available` field to `AskResponse` in `agent/runtime_agent.py` — the
  RBAC-permitted domain set for the caller's role, independent of what this question needed.
- `AnswerBubble.tsx` / `frontend/app/chat/page.tsx` now compute the "missed servers"
  warning from `servers_available`, not `servers_called`.

**Verified:** physician + radiology-only question → warning correctly gone. Nurse
(restricted role) + vitals question → warning still correctly shows (no regression).
Frontend type-checked clean (`tsc --noEmit`; the one remaining error is pre-existing in
`lib/auth.ts`, unrelated).

---

## 9. Dashboard "Status" badge never live-checked server health

**Symptom:** killed the `vitals_trends` process directly; the dashboard kept showing it as
**healthy** indefinitely.

**Root cause:** `mcp_servers.status` is a column written once at registration time
(hardcoded `"healthy"` string in `register.py`) and never updated automatically. The only
real check was the *manual* `register.py --health` command, and even that only wrote to a
separate `health_checks` table — the frontend's main colored badge and its "99%" health bar
(`pct = status === "healthy" ? 99 : 0` in `RegistryTable.tsx`) never read from it.

**Fix:** added a background health-check loop directly inside `registry-api`
(`backend/registry/main.py`), started on FastAPI startup:
- Every 20s (`HEALTH_CHECK_INTERVAL_SECONDS`, configurable), pings each registered server's
  real `/health` endpoint via `host.docker.internal` (same convention Kong already uses to
  reach host-run servers from inside a container).
- Updates `mcp_servers.status` + `updated_at` directly (what the dashboard badge reads) and
  still writes to `health_checks` (what the expandable per-row detail reads).
- New env vars added to `docker-compose.yml`: `HEALTH_CHECK_INTERVAL_SECONDS`,
  `MCP_SERVER_HOST`.

**Verified:** full round-trip — killed `vitals_trends`, badge flipped to **unhealthy**
within ~20s with no manual command; restarted it, badge flipped back to **healthy** within
the next cycle.

---

## 10. ⚠️ OPEN — "Registry API" / "Kong Gateway" sidebar lights are hardcoded green

**Symptom:** the chat page sidebar's "System Status" section shows three rows — Agent
online/offline, Registry API, Kong Gateway. Only the first one is real.

**Root cause:** [`frontend/app/chat/page.tsx:302-310`](../frontend/app/chat/page.tsx) renders
a static array (`[{label: "Registry API", port: 8600}, {label: "Kong Gateway", port: 8000}]`)
with a hardcoded green dot — no `fetch()`, no health check, ever. Only
`SystemStatusBadge` (the "Agent online" row) actually calls `/api/agent/health`.

**Status:** identified but **not yet fixed** — flagged during the "purpose of access"
verification pass. Would need the same pattern as `SystemStatusBadge`: a small
`fetch("/api/registry/servers")` (or a lightweight ping) per row, with loading/error states.

---

## Environment notes for whoever picks this up next

- Docker stack, the 5 MCP servers, the runtime agent, and the frontend UI were all
  intentionally stopped at the end of this session (`docker compose down`, process kills).
  Docker **volumes were left intact** — no data was lost.
- To resume: `docker compose up -d` → `bash scripts/start_mcp_servers.sh` →
  `uv run python -m backend.onboarding_agent.register --all` →
  `uv run uvicorn agent.runtime_agent:app --host 0.0.0.0 --port 8500` → `cd frontend && npm run dev`.
  See [`QUICK_TEST.md`](QUICK_TEST.md) for full command reference.
- `audit_events` was truncated (`TRUNCATE audit_events RESTART IDENTITY`) multiple times
  during testing to keep the dashboard clean — this is expected and harmless; it does not
  affect clinical data (vitals/labs/meds/diagnoses/notes/radiology), only the audit/anomaly
  history.
