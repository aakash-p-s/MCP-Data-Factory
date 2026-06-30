"""Register an approved blueprint into registry-db via registry-api `POST /servers`.

This is the BRIDGE between build-time and runtime: the onboarding agent writes a
blueprint.yaml (human approves it), this step records the server in the control plane
(registry-db), and the runtime agent then DISCOVERS it from the registry instead of a
hardcoded URL. Onboard a new domain → register it → the agent picks it up automatically.

Auth: uses the agent's own service identity (Keycloak client_credentials) — an infra call,
distinct from the user token the runtime agent forwards to the MCP servers.

  uv run python -m backend.onboarding_agent.register backend/servers/vitals_trends/blueprint.yaml
  uv run python -m backend.onboarding_agent.register --all      # register all 4 built servers
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
import yaml

REGISTRY_URL = os.getenv("REGISTRY_URL", "http://localhost:8600")
KEYCLOAK_ISSUER = os.getenv("KEYCLOAK_ISSUER", "http://localhost:8080/realms/patient-risk")
CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "patient-risk-agent")
CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "agent-secret-change-in-prod")

# domain → the port its MCP server listens on (host-run convention)
DOMAIN_PORT = {
    "vitals_trends": 8001,
    "labs_diagnoses": 8002,
    "medications_interactions": 8003,
    "clinical_notes_search": 8004,
    "radiology_reports": 8005,
}

REPO_ROOT = Path(__file__).resolve().parents[2]


def service_token() -> str:
    """Mint the agent's own Keycloak service token (client_credentials)."""
    r = httpx.post(f"{KEYCLOAK_ISSUER}/protocol/openid-connect/token",
                   data={"grant_type": "client_credentials",
                         "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
                   timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def register_blueprint(blueprint_path: str | Path, token: str | None = None) -> dict:
    """Read a blueprint.yaml and POST it to registry-api /servers."""
    bp = yaml.safe_load(Path(blueprint_path).read_text())
    domain = bp["domain"]
    payload = {
        "server_name": domain,
        "domain": domain,
        "status": "healthy",
        "kong_route": bp.get("kong_route"),
        "port": DOMAIN_PORT.get(domain),
    }
    token = token or service_token()
    r = httpx.post(f"{REGISTRY_URL}/servers", json=payload,
                   headers={"Authorization": f"Bearer {token}"}, timeout=10)
    r.raise_for_status()
    print(f"  registered {domain}  (route={payload['kong_route']} port={payload['port']})")
    return r.json()


def _all_blueprints() -> list[Path]:
    return sorted(REPO_ROOT.glob("backend/servers/*/blueprint.yaml"))


def main() -> None:
    args = sys.argv[1:]
    token = service_token()
    paths = _all_blueprints() if (not args or args[0] == "--all") else [Path(args[0])]
    print(f"[register] registry={REGISTRY_URL} | {len(paths)} blueprint(s)")
    for p in paths:
        register_blueprint(p, token)
    print("[register] done — runtime agent can now discover these via GET /servers")


if __name__ == "__main__":
    main()
