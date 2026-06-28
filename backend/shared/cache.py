"""30s TTL response cache — Codebase PRD §5.2.

Decorator for read-heavy async tool functions (get_vitals_trend, get_lab_trend). Caches by
the call's arguments for a short window so a repeated identical call is served from memory
(visibly faster trace). The first positional arg (the connector) is excluded from the key.
"""

from __future__ import annotations

import functools
import json
import time


def cached(ttl_seconds: int = 30):
    def decorator(fn):
        store: dict[tuple, tuple[float, object]] = {}

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            # key by args after the connector + kwargs (stable JSON repr)
            key = (json.dumps(args[1:], default=str, sort_keys=True),
                   json.dumps(kwargs, default=str, sort_keys=True))
            now = time.monotonic()
            entry = store.get(key)
            if entry is not None and now - entry[0] < ttl_seconds:
                return entry[1]
            result = await fn(*args, **kwargs)
            store[key] = (now, result)
            return result

        wrapper.cache_clear = store.clear  # handy for tests
        return wrapper

    return decorator
