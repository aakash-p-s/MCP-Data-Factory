#!/usr/bin/env python3
"""MCP Inspector smoke — live servers on localhost :8001–8004.

Run with all four MCP servers up (and AUTH_ALLOW_ANONYMOUS=false for production path):

    uv run python scripts/mcp_inspector_smoke.py

Optional: pass --in-process to use ASGI transport (no running servers needed).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
import jwt

PORTS = {
    "vitals_trends": 8001,
    "labs_diagnoses": 8002,
    "medications_interactions": 8003,
    "clinical_notes_search": 8004,
}

TOOLS = {
    "vitals_trends": ["get_vitals_trend", "compute_news2_score", "list_abnormal_vitals"],
    "labs_diagnoses": ["get_lab_trend", "get_active_diagnoses", "get_diagnosis_history"],
    "medications_interactions": ["get_active_medications", "check_drug_interactions", "get_polypharmacy_risk"],
    "clinical_notes_search": ["semantic_search_notes", "get_recent_notes", "get_notes_by_type"],
}

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
BODY = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


def _physician_token() -> str:
    return jwt.encode(
        {
            "sub": "inspector-physician",
            "scp": "mcp.vitals.read mcp.labs.read mcp.meds.read mcp.notes.read",
            "groups": ["grp-physician"],
        },
        "x" * 32,
        algorithm="HS256",
    )


async def _check_live(base_url: str, server: str) -> tuple[bool, str]:
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {_physician_token()}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        health = await client.get(f"{base_url}/health")
        if health.status_code != 200:
            return False, f"health {health.status_code}"
        resp = await client.post(f"{base_url}/mcp", headers=headers, json=BODY)
        if resp.status_code != 200:
            return False, f"tools/list {resp.status_code}: {resp.text[:200]}"
        missing = [t for t in TOOLS[server] if t not in resp.text]
        if missing:
            return False, f"missing tools: {missing}"
    return True, "ok"


async def _check_in_process(server: str) -> tuple[bool, str]:
    from backend.tests.rbac_fixtures import MCP_HEADERS, TOOLS_LIST_BODY, bearer_token, mcp_test_client

    headers = {**MCP_HEADERS, "Authorization": f"Bearer {bearer_token('physician')}"}
    with mcp_test_client(server) as client:
        resp = client.post("/mcp", headers=headers, json=TOOLS_LIST_BODY)
        if resp.status_code != 200:
            return False, f"tools/list {resp.status_code}"
        missing = [t for t in TOOLS[server] if t not in resp.text]
        if missing:
            return False, f"missing tools: {missing}"
    return True, "ok"


async def main(in_process: bool) -> int:
    os.environ.setdefault("AUTH_ALLOW_ANONYMOUS", "false")
    failed = 0
    for server, port in PORTS.items():
        if in_process:
            ok, msg = await _check_in_process(server)
            label = f"{server} (in-process)"
        else:
            ok, msg = await _check_live(f"http://localhost:{port}", server)
            label = f"{server} :{port}"
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {label} — {msg}")
        if not ok:
            failed += 1
    print(f"\n{len(PORTS) - failed}/{len(PORTS)} servers passed")
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MCP Inspector smoke for all 4 servers")
    parser.add_argument("--in-process", action="store_true", help="ASGI in-process (no live ports)")
    raise SystemExit(asyncio.run(main(parser.parse_args().in_process)))
