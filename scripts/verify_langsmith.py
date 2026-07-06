#!/usr/bin/env python3
"""Verify LangSmith tracing after a live /ask flow."""
from __future__ import annotations

import os
import pathlib
import sys
import time
from datetime import datetime, timezone

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_env() -> None:
    for line in (ROOT / ".env").read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    load_env()
    api_key = os.environ.get("LANGSMITH_API_KEY", "").strip()
    project = os.environ.get("LANGSMITH_PROJECT", "patient-risk").strip()
    tracing = os.environ.get("LANGSMITH_TRACING", "").lower()

    print("=== LangSmith config ===")
    print(f"  LANGSMITH_TRACING: {tracing}")
    print(f"  LANGSMITH_PROJECT: {project}")
    print(f"  LANGSMITH_API_KEY: {'set (' + api_key[:8] + '...)' if api_key else 'MISSING'}")

    if not api_key or tracing != "true":
        print("FAIL: LangSmith not fully configured in .env")
        return 1

    issuer = os.environ["KEYCLOAK_ISSUER"]
    token = httpx.post(
        f"{issuer}/protocol/openid-connect/token",
        data={
            "client_id": os.environ["KEYCLOAK_CLIENT_ID"],
            "client_secret": os.environ["KEYCLOAK_CLIENT_SECRET"],
            "username": "doctor-test",
            "password": "test123",
            "grant_type": "password",
            "scope": "openid",
        },
        timeout=15,
    ).json()["access_token"]

    print("\n=== Step 1: Agent health ===")
    health = httpx.get("http://localhost:8500/health", timeout=5)
    print(f"  agent -> {health.status_code}")
    if health.status_code != 200:
        print("FAIL: runtime agent not running on :8500")
        return 1

    print("\n=== Step 2: POST /ask (triggers LangChain trace) ===")
    before = time.time()
    ask = httpx.post(
        "http://localhost:8500/ask",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "question": "What is demo-patient-1 NEWS2 score?",
            "patient_id": "demo-patient-1",
            "purpose_of_access": "deterioration_review",
        },
        timeout=120,
    )
    print(f"  /ask -> {ask.status_code}")
    if ask.status_code != 200:
        print(ask.text[:500])
        return 1
    body = ask.json()
    print(f"  servers_called: {body.get('servers_called')}")
    print(f"  answer preview: {body.get('answer', '')[:120]}...")

    print("\n=== Step 3: Query LangSmith for recent runs ===")
    time.sleep(3)  # allow async trace upload
    try:
        from langsmith import Client
    except ImportError:
        print("FAIL: langsmith package not installed")
        return 1

    client = Client(api_key=api_key)
    recent = list(
        client.list_runs(
            project_name=project,
            is_root=True,
            start_time=datetime.fromtimestamp(before - 60, tz=timezone.utc),
            limit=5,
        )
    )
    if not recent:
        print("FAIL: No root runs found in LangSmith project after /ask")
        print(f"  Check manually: https://smith.langchain.com/o/-/projects/p/{project}")
        return 1

    latest = recent[0]
    print(f"  Latest trace: {latest.name}")
    print(f"  Run id:       {latest.id}")
    print(f"  Status:       {latest.status}")
    print(f"  Start time:   {latest.start_time}")
    child_count = latest.child_run_ids or []
    print(f"  Child runs:   {len(child_count)}")

    print("\nLANGSMITH TRACE OK")
    print(f"  View at: https://smith.langchain.com/o/-/projects/p/{project}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
