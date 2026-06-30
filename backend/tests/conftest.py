"""Pytest config — repo root on sys.path so `backend.*` imports resolve."""

import os
import sys
from pathlib import Path

# Enforce production auth path before server modules import middleware.
os.environ.setdefault("AUTH_ALLOW_ANONYMOUS", "false")
# In-process tests use self-signed (forged) tokens — force signature verification OFF here
# regardless of a hardened .env (which sets AUTH_VERIFY_SIGNATURE=true for the live runtime).
os.environ["AUTH_VERIFY_SIGNATURE"] = "false"

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest_plugins = ("pytest_asyncio",)
