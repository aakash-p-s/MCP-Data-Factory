#!/usr/bin/env python3
"""Pre-push verification — data stores, 4 MCP servers, RBAC, and live tool calls.

Usage (servers must be running on :8001–8004 with .env loaded):

    uv run python scripts/pre_push_verify.py

Exit 0 = all checks passed; 1 = one or more failures.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import jwt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.tests.rbac_fixtures import ACCESS, SERVER_PORTS, SERVER_SPECS, bearer_token

SECRET = "x" * 32
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
TOOLS_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
DEMO_PATIENT = "demo-patient-1"

# One representative tool call per server (minimal args)
TOOL_CALLS = {
    "vitals_trends": {
        "method": "tools/call",
        "params": {"name": "get_vitals_trend", "arguments": {"patient_id": DEMO_PATIENT, "hours": 24}},
    },
    "labs_diagnoses": {
        "method": "tools/call",
        "params": {"name": "get_lab_trend", "arguments": {"patient_id": DEMO_PATIENT, "test_name": "Glucose"}},
    },
    "medications_interactions": {
        "method": "tools/call",
        "params": {"name": "get_active_medications", "arguments": {"patient_id": DEMO_PATIENT}},
    },
    "clinical_notes_search": {
        "method": "tools/call",
        "params": {"name": "get_recent_notes", "arguments": {"patient_id": DEMO_PATIENT, "limit": 3}},
    },
}


class Check:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.lines: list[str] = []

    def ok(self, name: str, detail: str = "ok") -> None:
        self.passed += 1
        self.lines.append(f"[PASS] {name} — {detail}")

    def fail(self, name: str, detail: str) -> None:
        self.failed += 1
        self.lines.append(f"[FAIL] {name} — {detail}")

    def report(self) -> int:
        for line in self.lines:
            print(line)
        print(f"\n{self.passed}/{self.passed + self.failed} checks passed")
        return 1 if self.failed else 0


def run_pytest() -> tuple[bool, str]:
    r = subprocess.run(
        ["uv", "run", "pytest", "backend/tests/", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    tail = (r.stdout or r.stderr).strip().splitlines()[-1] if r.stdout or r.stderr else "no output"
    return r.returncode == 0, tail


async def check_health(client: httpx.AsyncClient, server: str, port: int, chk: Check) -> None:
    try:
        r = await client.get(f"http://localhost:{port}/health")
        if r.status_code != 200:
            chk.fail(f"{server} /health", f"HTTP {r.status_code}")
            return
        info = r.json()
        if not info.get("fixed_core"):
            chk.fail(f"{server} /health", "fixed_core not true")
            return
        if info.get("tools") != SERVER_SPECS[server]["tools"]:
            chk.fail(f"{server} /health", f"tools mismatch: {info.get('tools')}")
            return
        chk.ok(f"{server} /health", f":{port} fixed_core=true, 3 tools")
    except Exception as exc:
        chk.fail(f"{server} /health", str(exc))


async def check_tools_list(client: httpx.AsyncClient, server: str, port: int, role: str, chk: Check) -> None:
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {bearer_token(role)}"}
    try:
        r = await client.post(f"http://localhost:{port}/mcp", headers=headers, json=TOOLS_LIST)
        expect = ACCESS[role][server]
        if expect and r.status_code != 200:
            chk.fail(f"{server} tools/list ({role})", f"expected 200, got {r.status_code}")
            return
        if not expect and r.status_code != 403:
            chk.fail(f"{server} tools/list ({role})", f"expected 403, got {r.status_code}")
            return
        if expect:
            missing = [t for t in SERVER_SPECS[server]["tools"] if t not in r.text]
            if missing:
                chk.fail(f"{server} tools/list ({role})", f"missing tools: {missing}")
                return
        chk.ok(f"{server} RBAC ({role})", "allow" if expect else "deny 403")
    except Exception as exc:
        chk.fail(f"{server} tools/list ({role})", str(exc))


async def check_tool_call(client: httpx.AsyncClient, server: str, port: int, chk: Check) -> None:
    body = {"jsonrpc": "2.0", "id": 2, **TOOL_CALLS[server]}
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {bearer_token('physician')}"}
    try:
        r = await client.post(f"http://localhost:{port}/mcp", headers=headers, json=body, timeout=60.0)
        if r.status_code != 200:
            chk.fail(f"{server} tool call", f"HTTP {r.status_code}: {r.text[:200]}")
            return
        if "error" in r.text and "result" not in r.text:
            chk.fail(f"{server} tool call", r.text[:300])
            return
        tool = TOOL_CALLS[server]["params"]["name"]
        chk.ok(f"{server} tool call ({tool})", "200 with result")
    except Exception as exc:
        chk.fail(f"{server} tool call", str(exc))


async def check_no_token(client: httpx.AsyncClient, chk: Check) -> None:
    try:
        r = await client.post(
            f"http://localhost:{SERVER_PORTS['vitals_trends']}/mcp",
            headers=MCP_HEADERS,
            json=TOOLS_LIST,
        )
        if r.status_code == 401:
            chk.ok("auth no-token", "401 unauthorized")
        else:
            chk.fail("auth no-token", f"expected 401, got {r.status_code}")
    except Exception as exc:
        chk.fail("auth no-token", str(exc))


async def main() -> int:
    os.environ.setdefault("AUTH_ALLOW_ANONYMOUS", "false")
    chk = Check()

    ok, tail = run_pytest()
    if ok:
        chk.ok("pytest suite", tail)
    else:
        chk.fail("pytest suite", tail)

    async with httpx.AsyncClient(timeout=30.0) as client:
        for server, port in SERVER_PORTS.items():
            await check_health(client, server, port, chk)

        # RBAC spot-check: nurse allowed vitals, denied meds; case-manager notes only
        await check_tools_list(client, "vitals_trends", 8001, "clinical-viewer", chk)
        await check_tools_list(client, "medications_interactions", 8003, "clinical-viewer", chk)
        await check_tools_list(client, "clinical_notes_search", 8004, "case-manager", chk)
        await check_tools_list(client, "vitals_trends", 8001, "case-manager", chk)
        await check_no_token(client, chk)

        for server, port in SERVER_PORTS.items():
            await check_tool_call(client, server, port, chk)

    return chk.report()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
