# Patient Risk Intelligence — Frontend

Next.js 14 + NextAuth + CopilotKit + Tremor clinician-facing UI.

## What this builds

| Route | Purpose |
|---|---|
| `/` | Session check → login card or redirect to `/chat` |
| `/chat` | Clinician chat, calls `POST /ask` on the runtime agent |
| `/dashboard` | Registry table + KPI cards + anomaly panel |

## Prerequisites

- Node.js 20
- npm 9+
- The backend must be running (agent :8500, registry-api :8600, Keycloak :8080)

## Setup — first time only

**Step 1 — Copy the env file:**

```bash
cp .env.local.example .env.local
```

The values in `.env.local.example` are already correct for local development — no changes needed unless you changed any ports.

**Step 2 — Install dependencies:**

```bash
npm install
```

**Step 3 — Start the dev server:**

```bash
npm run dev
```

Open `http://localhost:3000` — you should see the login card.

**Step 4 — Sign in:**

Click **"Sign in with Keycloak SSO"** and use one of the demo accounts shown on screen:

| Username | Password | Role |
|---|---|---|
| doctor-test | test123 | Physician (full access) |
| nurse-test | test123 | Clinical Viewer (vitals + labs only) |
| casemanager-test | test123 | Case Manager (notes only) |

## Daily usage

```bash
cd frontend
npm run dev
```

Make sure the backend is up first:
```bash
# From the project root
docker compose up -d
bash scripts/start_mcp_servers.sh
uv run uvicorn agent.runtime_agent:app --host 0.0.0.0 --port 8500
```

## Docker (full stack)

When you are ready to run the full stack via Docker:

```bash
# From the project root
docker compose --profile full up -d
```

This starts: Keycloak, Kong, registry-api, registry-db, agent, **and** the frontend.

The frontend Dockerfile uses a multi-stage build (node:20-alpine builder → standalone runner).
`next.config.js` must have `output: "standalone"` — already set.

## File structure

```
frontend/
├── app/
│   ├── layout.tsx                      # SessionProvider + Nav
│   ├── page.tsx                        # Login card / redirect
│   ├── chat/page.tsx                   # Chat page → POST /ask
│   ├── dashboard/page.tsx              # Dashboard shell
│   └── api/auth/[...nextauth]/route.ts # NextAuth ↔ Keycloak
├── components/
│   ├── PurposeSelector.tsx             # 5-value purpose dropdown
│   ├── PatientPicker.tsx               # demo-patient-1 … 31
│   ├── AnswerBubble.tsx                # cited answer with server pills
│   ├── RegistryTable.tsx              # polls GET /servers every 5s
│   └── AnomalyPanel.tsx               # 5 heuristics from GET /audit
├── lib/
│   └── next-auth.d.ts                 # TypeScript augmentation for session
├── .env.local.example                 # copy to .env.local
├── next.config.js                     # standalone output for Docker
├── tailwind.config.ts
├── tsconfig.json
└── Dockerfile
```

## How the data flows

```
Browser
  │
  ├─ Login → NextAuth → Keycloak :8080 (OIDC authorization code)
  │            ↓ stores accessToken in session cookie
  │
  ├─ Chat POST /ask → Runtime Agent :8500 (Bearer JWT)
  │                      ↓ (service token, infra call)
  │                   Registry API :8600 (GET /servers)
  │                      ↓ (user Bearer JWT forwarded)
  │                   Kong :8000 → MCP servers :8001-8005
  │
  ├─ Dashboard GET /servers → Registry API :8600 (Bearer JWT)
  ├─ Dashboard GET /audit  → Registry API :8600 (Bearer JWT)
  │
  └─ Jaeger trace links → http://localhost:16686/trace/{trace_id}
     (opens in new tab, no API call from browser)
```

**The browser NEVER calls Kong or MCP servers directly.**
Only `agent :8500` and `registry-api :8600` are called from browser code.

## Acceptance checklist (verified Jul 6, 2026)

- [x] NextAuth login works at http://localhost:3000
- [x] `/chat` sends POST /ask with Bearer token + purpose_of_access
- [x] Physician gets a cited 5-server answer for demo-patient-1
- [x] Nurse sees partial answer (meds/notes denied gracefully)
- [x] `/dashboard` shows 5 server rows, all healthy
- [x] KPI cards show counts
- [x] Anomaly panel shows heuristics (populate by making a few /ask calls first)
- [x] Trace IDs link to Jaeger
- [x] `docker compose --profile full up -d` brings everything up

## Troubleshooting

| Problem | Fix |
|---|---|
| Login redirects to error page | Check `KEYCLOAK_ISSUER` in `.env.local` matches `http://localhost:8080/realms/patient-risk` |
| Chat returns 401 | Session expired — sign out and sign back in |
| Chat returns "Cannot reach agent" | Start the agent: `uv run uvicorn agent.runtime_agent:app --host 0.0.0.0 --port 8500` |
| Dashboard shows 0 servers | Run `uv run python -m backend.onboarding_agent.register --all` first |
| `npm run build` fails | Run `npm install` — delete `node_modules/` and reinstall if needed |
| Keycloak callback error | Ensure `http://localhost:3000/api/auth/callback/keycloak` is in Keycloak's valid redirect URIs |
