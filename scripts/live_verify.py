#!/usr/bin/env python3
"""Quick live verification — data path + agent /ask."""

from __future__ import annotations

import json
import sys

import httpx

PORTS = [
    (8001, "vitals_trends"),
    (8002, "labs_diagnoses"),
    (8003, "medications_interactions"),
    (8004, "clinical_notes_search"),
]


def main() -> int:
    print("=== Step 1: MCP server health ===")
    for port, name in PORTS:
        r = httpx.get(f"http://localhost:{port}/health", timeout=5)
        svc = r.json().get("service", "ok")
        print(f"  :{port} {name} -> {r.status_code} {svc}")

    print("\n=== Step 2: Agent health ===")
    r = httpx.get("http://localhost:8500/health", timeout=5)
    h = r.json()
    print(f"  agent -> {r.status_code}")
    print(f"  MCP URLs: {json.dumps(h['servers'], indent=2)}")
    print(f"  aliases loaded: {h['demo_aliases_loaded']}")

    print("\n=== Step 3: Keycloak token (doctor-test) ===")
    t = httpx.post(
        "http://localhost:8080/realms/patient-risk/protocol/openid-connect/token",
        data={
            "client_id": "patient-risk-agent",
            "client_secret": "agent-secret-change-in-prod",
            "username": "doctor-test",
            "password": "test123",
            "grant_type": "password",
            "scope": "openid",
        },
        timeout=15,
    )
    print(f"  token -> {t.status_code}")
    if t.status_code != 200:
        print(t.text)
        return 1
    token = t.json()["access_token"]

    print("\n=== Step 4: POST /ask (live E2E) ===")
    ask = httpx.post(
        "http://localhost:8500/ask",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "question": "What is this patient overall risk picture?",
            "patient_id": "demo-patient-1",
            "purpose_of_access": "deterioration_review",
        },
        timeout=120,
    )
    print(f"  /ask -> {ask.status_code}")
    if ask.status_code != 200:
        print(ask.text[:1000])
        return 1
    body = ask.json()
    print(f"  servers_called: {body.get('servers_called')}")
    print(f"  patient_uuid: {body.get('patient_uuid')}")
    print(f"\n  answer:\n{body.get('answer', '')}\n")
    print("LIVE VERIFY OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
