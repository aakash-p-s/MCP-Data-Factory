"""Pytest config — repo root on sys.path so `backend.*` imports resolve."""

import os
import sys
from pathlib import Path

# Enforce production auth path before server modules import middleware.
os.environ.setdefault("AUTH_ALLOW_ANONYMOUS", "false")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest_plugins = ("pytest_asyncio",)
