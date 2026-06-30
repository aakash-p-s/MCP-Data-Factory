"""SSRF / egress guard — Codebase PRD §5.3.

Each server gets its connector ONLY via locked_connector_for(server_name): the backend
URL is resolved here from a fixed allow-list and bound at construction. A server has no
code path to build a connector pointed at an arbitrary URL — closing the Fixed Core
SSRF/egress gap.
"""

from __future__ import annotations

import os

from backend.connectors.sql_connector import SQLConnector
from backend.connectors.vector_connector import VectorConnector
from backend.shared.connector_base import Connector

_SQL_BACKENDS = {
    "vitals_trends": ("VITALS_DB_URL", "postgresql://postgres:changeme@localhost:5433/vitals"),
    "labs_diagnoses": ("CLINICAL_DB_URL", "postgresql://postgres:changeme@localhost:5434/clinical"),
    "medications_interactions": ("CLINICAL_DB_URL", "postgresql://postgres:changeme@localhost:5434/clinical"),
<<<<<<< HEAD
    "radiology_reports": ("CLINICAL_DB_URL", "postgresql://postgres:changeme@localhost:5434/clinical"), #<--ADDED FOR TESTING THE ONBOARDING AGENT
=======
    "radiology_reports": ("CLINICAL_DB_URL", "postgresql://postgres:changeme@localhost:5434/clinical"),  # onboarding-agent demo domain
>>>>>>> 1caa326 (feat: pull onboarding agent (build-time) onto clean branch + verify against data layer)
}

_VECTOR_BACKENDS = {
    "clinical_notes_search": ("QDRANT_URL", "http://localhost:6333"),
}


def locked_connector_for(server_name: str) -> Connector:
    """Return the only connector type allowed for this server (DSN/URL fixed at construction)."""
    if server_name in _SQL_BACKENDS:
        env_var, default = _SQL_BACKENDS[server_name]
        return SQLConnector(os.environ.get(env_var, default))
    if server_name in _VECTOR_BACKENDS:
        env_var, default = _VECTOR_BACKENDS[server_name]
        return VectorConnector(os.environ.get(env_var, default))
    raise KeyError(f"no egress-allowed backend registered for {server_name!r}")
