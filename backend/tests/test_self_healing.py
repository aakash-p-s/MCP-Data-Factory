"""Self-healing / chaos tests — transient failure recovery (Jul 7).

Simulates stale pools and backend blips; verifies tenacity retries + connector reset
without restarting the MCP server process.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import asyncpg
import pytest

from backend.connectors.sql_connector import SQLConnector
from backend.shared.self_healing import is_transient, run_with_self_healing


def test_is_transient_recognises_connection_errors():
    assert is_transient(ConnectionError("reset"))
    assert is_transient(asyncpg.PostgresConnectionError("gone"))
    assert not is_transient(ValueError("bad sql"))


def test_run_with_self_healing_retries_then_succeeds():
    calls = 0

    async def flaky():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionError("simulated blip")
        return "ok"

    result = asyncio.run(run_with_self_healing(flaky, attempts=3))
    assert result == "ok"
    assert calls == 3


def test_run_with_self_healing_invokes_reset_on_transient_failure():
    calls = 0
    resets = 0

    async def flaky():
        nonlocal calls
        calls += 1
        if calls < 2:
            raise OSError("connection reset")
        return 42

    async def reset():
        nonlocal resets
        resets += 1

    result = asyncio.run(run_with_self_healing(flaky, reset=reset, attempts=3))
    assert result == 42
    assert calls == 2
    assert resets == 1


def test_run_with_self_healing_does_not_retry_logic_errors():
    calls = 0

    async def bad():
        nonlocal calls
        calls += 1
        raise ValueError("validation failed")

    with pytest.raises(ValueError, match="validation"):
        asyncio.run(run_with_self_healing(bad, attempts=3))
    assert calls == 1


def test_sql_connector_retries_after_simulated_pool_failure():
    """Chaos demo: first fetch throws a transient DB error, second succeeds."""
    conn = SQLConnector("postgresql://unused")
    attempts = 0

    async def fake_fetch(sql, *args):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise asyncpg.ConnectionDoesNotExistError("pool stale")
        return [{"n": 1}]

    fake_pool = MagicMock()
    fake_pool.fetch = fake_fetch

    async def fake_close():
        conn.pool = None

    fake_pool.close = fake_close

    async def fake_open():
        conn.pool = fake_pool

    conn.pool = fake_pool
    conn._open_pool = fake_open  # noqa: SLF001 — test double

    async def run():
        return await conn.query({"sql": "SELECT 1 AS n", "args": []})

    rows = asyncio.run(run())
    assert rows == [{"n": 1}]
    assert attempts == 2
