"""SQLConnector — Codebase PRD §5.3.

Concrete Connector for TimescaleDB/Postgres, shared by vitals_trends, labs_diagnoses,
and medications_interactions. Behind the SAME interface as VectorConnector (Qdrant) —
that is the architecture's pluggable-connector proof.

connect() opens an asyncpg pool to a fixed DSN (bound at construction — the server has no
path to point it elsewhere, which is the egress-guard intent). query() runs ONLY
parameterized, read-only SELECTs (query guardrails §6.6) — never raw string interpolation.
"""

from __future__ import annotations

import re

import asyncpg

from backend.shared.connector_base import Connector
from backend.shared.self_healing import run_with_self_healing

# query guardrail: block any write/DDL statement (§6.6)
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|merge|create|grant|revoke|copy)\b",
    re.IGNORECASE,
)


def _assert_read_only(sql: str) -> None:
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        raise ValueError("multiple statements are not allowed")
    if not stripped.lower().startswith(("select", "with")):
        raise ValueError("only read-only SELECT/WITH queries are allowed")
    if _FORBIDDEN.search(stripped):
        raise ValueError("write/DDL keywords are not allowed in a read query")


class SQLConnector(Connector):
    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 5):
        self._dsn = dsn                      # fixed at construction (egress guard intent)
        self._min, self._max = min_size, max_size
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        await run_with_self_healing(self._open_pool, reset=self._reset_pool)

    async def _open_pool(self) -> None:
        if self.pool is None:
            self.pool = await asyncpg.create_pool(
                self._dsn, min_size=self._min, max_size=self._max)

    async def _reset_pool(self) -> None:
        await self.close()

    async def auth(self) -> None:
        # credentials are carried in the DSN; nothing extra to do for Postgres.
        return None

    async def schema(self) -> dict:
        """Introspect tables/columns from information_schema."""
        return await run_with_self_healing(self._schema_once, reset=self._reset_pool)

    async def _schema_once(self) -> dict:
        await self.connect()
        rows = await self.pool.fetch(
            """SELECT table_name, column_name, data_type
               FROM information_schema.columns
               WHERE table_schema = 'public'
               ORDER BY table_name, ordinal_position""")
        out: dict[str, list] = {}
        for r in rows:
            out.setdefault(r["table_name"], []).append(
                {"column": r["column_name"], "type": r["data_type"]})
        return out

    async def query(self, params: dict) -> list[dict]:
        """Run a parameterized read-only query.

        params = {"sql": "SELECT ... WHERE patient_id = $1", "args": [...]}
        """
        return await run_with_self_healing(
            lambda: self._query_once(params), reset=self._reset_pool)

    async def _query_once(self, params: dict) -> list[dict]:
        sql = params["sql"]
        args = params.get("args", [])
        _assert_read_only(sql)
        await self.connect()
        rows = await self.pool.fetch(sql, *args)
        return [dict(r) for r in rows]

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None
