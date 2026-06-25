"""vitals_trends — DAY-1 STUB SERVER (Person A PRD §6.1).

Person B's Runtime Agent work is blocked without this. The contract here is FIXED
(Codebase PRD §6.2 / §6.5):

    tools : get_vitals_trend, compute_news2_score, list_abnormal_vitals
    scope : mcp.vitals.read
    route : /mcp/clinical/vitals-trends/dev   (Kong; direct MCP endpoint is /mcp)
    ok    : FHIR R4 Observation JSON
    deny  : HTTP 403 {"error":{"code":"forbidden","reason":"missing scope mcp.vitals.read"}}

"Fake data, real shape." Everything returned here is HARDCODED — no DB. The real
DB-backed server replaces this on Jun 29; tool names/shape will NOT change.

Real JWT signature verification + full group/scope RBAC land Jul 2 (backend/shared/auth.py).
For the stub: a request WITH a bearer token missing the scope gets the 403 envelope;
a request with no token is allowed (so Person B can integrate before Keycloak is wired).

Run:  uv run python backend/servers/vitals_trends/main.py   # -> http://localhost:8001/mcp
"""

from __future__ import annotations

import json
import os

import jwt
from mcp.server.fastmcp import FastMCP

PORT = int(os.getenv("VITALS_PORT", "8001"))
REQUIRED_SCOPE = "mcp.vitals.read"

mcp = FastMCP("vitals_trends", stateless_http=True)


# --- FHIR helper (inlined for the stub; shared fhir_shape.py arrives later) ---
def _observation(patient_id: str, loinc: str, display: str, value, unit: str,
                 ts: str, interpretation: str | None = None) -> dict:
    obs = {
        "resourceType": "Observation",
        "status": "final",
        "category": [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
            "code": "vital-signs", "display": "Vital Signs"}]}],
        "code": {"coding": [{"system": "http://loinc.org", "code": loinc,
                             "display": display}], "text": display},
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": ts,
        "valueQuantity": {"value": value, "unit": unit,
                          "system": "http://unitsofmeasure.org", "code": unit},
    }
    if interpretation:
        obs["interpretation"] = [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
            "code": interpretation}]}]
    return obs


# --- tools (hardcoded; real tool names + real FHIR shape) ---------------------
@mcp.tool()
def get_vitals_trend(patient_id: str, hours: int = 24) -> list[dict]:
    """Recent vital-sign Observations for a patient (STUB: hardcoded)."""
    return [
        _observation(patient_id, "8867-4", "Heart rate", 88, "/min", "2026-06-26T08:00:00Z"),
        _observation(patient_id, "8867-4", "Heart rate", 95, "/min", "2026-06-26T12:00:00Z"),
        _observation(patient_id, "9279-1", "Respiratory rate", 20, "/min", "2026-06-26T12:00:00Z"),
        _observation(patient_id, "2708-6", "Oxygen saturation", 94, "%", "2026-06-26T12:00:00Z"),
        _observation(patient_id, "8480-6", "Systolic blood pressure", 132, "mm[Hg]", "2026-06-26T12:00:00Z"),
    ]


@mcp.tool()
def compute_news2_score(patient_id: str) -> dict:
    """NEWS2 deterioration score + risk band (STUB: hardcoded)."""
    return {
        "patient_id": patient_id,
        "news2_score": 6,
        "risk_band": "medium",
        "components": {"resp_rate": 2, "spo2": 2, "temperature": 0,
                       "systolic_bp": 1, "heart_rate": 1, "consciousness": 0},
        "note": "STUB — fixed score; real NEWS2 computed from vitals on Jun 29",
    }


@mcp.tool()
def list_abnormal_vitals(patient_id: str, hours: int = 24) -> list[dict]:
    """Vital-sign Observations outside normal range (STUB: hardcoded)."""
    return [
        _observation(patient_id, "2708-6", "Oxygen saturation", 94, "%",
                     "2026-06-26T12:00:00Z", interpretation="L"),
        _observation(patient_id, "9279-1", "Respiratory rate", 22, "/min",
                     "2026-06-26T12:00:00Z", interpretation="H"),
    ]


# --- Layer-2 scope guard (ASGI; emits the exact 403 envelope) -----------------
class ScopeGuard:
    """Pure-ASGI guard so it never buffers MCP's streaming responses.

    Stub behavior: a bearer token missing REQUIRED_SCOPE -> 403 envelope.
    No token -> allowed (POC-friendly). Signature verification is added Jul 2.
    """

    def __init__(self, app, required_scope: str):
        self.app = app
        self.required = required_scope

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            if auth.lower().startswith("bearer "):
                try:
                    claims = jwt.decode(auth[7:], options={"verify_signature": False})
                except Exception:
                    claims = {}
                scopes = (claims.get("scp") or "").split()
                if self.required not in scopes:
                    body = json.dumps({"error": {"code": "forbidden",
                        "reason": f"missing scope {self.required}"}}).encode()
                    await send({"type": "http.response.start", "status": 403,
                                "headers": [(b"content-type", b"application/json"),
                                            (b"content-length", str(len(body)).encode())]})
                    await send({"type": "http.response.body", "body": body})
                    return
        await self.app(scope, receive, send)


app = ScopeGuard(mcp.streamable_http_app(), REQUIRED_SCOPE)


if __name__ == "__main__":
    from importlib.metadata import PackageNotFoundError, version

    import uvicorn

    try:
        mcp_version = version("mcp")          # the SDK has no module __version__
    except PackageNotFoundError:
        mcp_version = "unknown"
    print(f"[vitals_trends STUB] MCP SDK {mcp_version} "
          f"| endpoint http://localhost:{PORT}/mcp "
          f"| scope={REQUIRED_SCOPE} | route=/mcp/clinical/vitals-trends/dev",
          flush=True)   # flush so the banner shows in redirected/Docker logs
    uvicorn.run(app, host="0.0.0.0", port=PORT)
