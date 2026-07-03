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

import ast
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


_TYPE_MAP = {"str": "string", "int": "integer", "float": "number", "bool": "boolean"}


def _annotation_to_json_type(ann: ast.expr | None) -> str:
    """Best-effort Python-annotation -> JSON-Schema-type mapping for the blueprint's
    human-written `signature` strings (e.g. "str", "int", "str | None")."""
    if ann is None:
        return "string"
    if isinstance(ann, ast.Name):
        return _TYPE_MAP.get(ann.id, "string")
    if isinstance(ann, ast.BinOp):   # e.g. `str | None` — every observed case has the
        return _annotation_to_json_type(ann.left)   # real type on the left, None on the right
    if isinstance(ann, ast.Subscript):  # e.g. list[Observation] — only ever in the return type here
        return "array"
    return "string"


def signature_to_schema(signature: str) -> dict:
    """Parse a blueprint tool `signature` string, e.g.
    "(patient_id: str, hours: int = 24) -> list[Observation]", into a JSON Schema
    object describing its parameters — this is what lets the runtime agent build a
    correct tool call WITHOUT connecting to the live MCP server just to ask it.
    """
    stub = f"def _tool{signature}:\n    pass\n"
    try:
        tree = ast.parse(stub)
        fn = tree.body[0]
    except SyntaxError:
        return {"type": "object", "properties": {}, "required": []}

    args = fn.args.args
    defaults = fn.args.defaults
    n_required = len(args) - len(defaults)
    properties: dict[str, dict] = {}
    required: list[str] = []
    for i, a in enumerate(args):
        prop: dict = {"type": _annotation_to_json_type(a.annotation)}
        if i >= n_required:
            default_node = defaults[i - n_required]
            try:
                default_val = ast.literal_eval(default_node)
                if default_val is not None:
                    prop["default"] = default_val
            except (ValueError, TypeError):
                pass
        else:
            required.append(a.arg)
        properties[a.arg] = prop
    return {"type": "object", "properties": properties, "required": required}


def register_blueprint(blueprint_path: str | Path, token: str | None = None) -> dict:
    """Read a blueprint.yaml and POST it to registry-api /servers."""
    bp = yaml.safe_load(Path(blueprint_path).read_text())
    domain = bp["domain"]
    tool_defs = []
    for t in bp.get("tools", []):
        if not t.get("name"):
            continue
        entry = {"name": t["name"]}
        sig = t.get("signature")
        if sig:
            entry["input_schema"] = signature_to_schema(sig)
            entry["description"] = f"{t['name']}{sig}"
        tool_defs.append(entry)
    payload = {
        "server_name": domain,
        "domain": domain,
        "status": "healthy",
        "kong_route": bp.get("kong_route"),
        "port": DOMAIN_PORT.get(domain),
        "scope": bp.get("scope"),
        "tools": tool_defs,
        "rbac": bp.get("rbac", {}),   # {role_name: allow|deny} → tool_specs + rbac_mappings
    }
    token = token or service_token()
    r = httpx.post(f"{REGISTRY_URL}/servers", json=payload,
                   headers={"Authorization": f"Bearer {token}"}, timeout=10)
    r.raise_for_status()
    print(f"  registered {domain}  (route={payload['kong_route']} port={payload['port']})")
    return r.json()


def health_sweep() -> None:
    """Ping each registered server's /health and record a row in health_checks."""
    import time

    import psycopg

    db_url = os.environ.get("REGISTRY_DB_URL")
    if not db_url:
        sys.exit("REGISTRY_DB_URL required for the health sweep")
    token = service_token()
    servers = httpx.get(f"{REGISTRY_URL}/servers",
                        headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
    db = psycopg.connect(db_url, autocommit=True)
    print(f"[health] sweeping {len(servers)} servers")
    for s in servers:
        port = s.get("port")
        if not port:
            continue
        t = time.perf_counter()
        status, err = "healthy", None
        try:
            r = httpx.get(f"http://localhost:{port}/health", timeout=3)
            if r.status_code != 200:
                status, err = "unhealthy", f"HTTP {r.status_code}"
        except Exception as exc:
            status, err = "unhealthy", str(exc)[:120]   # status CHECK allows only healthy/unhealthy
        latency = int((time.perf_counter() - t) * 1000)
        db.execute("INSERT INTO health_checks (server_id, status, latency_ms, error_msg) "
                   "VALUES (%s, %s, %s, %s)", (s["server_id"], status, latency, err))
        print(f"  {s['domain']:26} {status:9} {latency}ms")


def _all_blueprints() -> list[Path]:
    return sorted(REPO_ROOT.glob("backend/servers/*/blueprint.yaml"))


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "--health":
        health_sweep()
        return
    token = service_token()
    paths = _all_blueprints() if (not args or args[0] == "--all") else [Path(args[0])]
    print(f"[register] registry={REGISTRY_URL} | {len(paths)} blueprint(s)")
    for p in paths:
        register_blueprint(p, token)
    print("[register] done — runtime agent can now discover these via GET /servers")


if __name__ == "__main__":
    main()
