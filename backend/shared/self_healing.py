"""Self-healing retries — Codebase PRD §5.2.

Tenacity-backed retry for transient backend failures (stale pool, connection reset,
Qdrant unreachable). Connectors call run_with_self_healing() around query operations;
an optional reset callback drops the pool/client so the next attempt reconnects fresh.

Docker `restart: unless-stopped` handles process-level recovery; this module handles
in-process blips without restarting the MCP server.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import TypeVar

from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

T = TypeVar("T")

MAX_ATTEMPTS = int(os.getenv("SELF_HEAL_MAX_ATTEMPTS", "3"))


def is_transient(exc: BaseException) -> bool:
    """True for errors worth retrying (not auth/validation/logic failures)."""
    if isinstance(exc, (ConnectionError, OSError, TimeoutError)):
        return True
    try:
        import asyncpg
        if isinstance(exc, (
            asyncpg.PostgresConnectionError,
            asyncpg.InterfaceError,
            asyncpg.CannotConnectNowError,
            asyncpg.ConnectionDoesNotExistError,
        )):
            return True
    except ImportError:
        pass
    # qdrant_client wraps HTTP failures in response/connection errors
    mod = type(exc).__module__ or ""
    if "qdrant" in mod and type(exc).__name__ in {
        "ResponseHandlingException", "UnexpectedResponse", "Urllib3HttpClientException",
    }:
        return True
    return False


async def run_with_self_healing(
    operation: Callable[[], Awaitable[T]],
    *,
    reset: Callable[[], Awaitable[None]] | None = None,
    attempts: int | None = None,
) -> T:
    """Run an async operation; retry transient failures with exponential backoff."""
    n = attempts if attempts is not None else MAX_ATTEMPTS
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(n),
        wait=wait_exponential(multiplier=0.2, min=0.2, max=2.0),
        retry=retry_if_exception(is_transient),
        reraise=True,
    ):
        with attempt:
            try:
                return await operation()
            except Exception as exc:
                if reset is not None and is_transient(exc):
                    await reset()
                raise
