"""
backend/onboarding_agent/

Build-time onboarding agent (Codebase PRD §5.5).

One process, four internal stages, run once per new domain:

    discover.py            -> discover_schema(connector) -> {"raw", "fhir_shape"}
    suggest_tools.py        -> suggest_tools(domain, schema) -> list[dict]
    draft_rbac.py            -> draft_rbac(domain, tools) -> dict
    assemble_blueprint.py    -> assemble_blueprint(domain, schema, tools, rbac) -> Path

run.py orchestrates all four for a given domain. Output is a single
blueprint.yaml file — this agent never deploys anything, never touches
Kong, the registry, or any database beyond a read-only schema() call.
"""

from backend.onboarding_agent.assemble_blueprint import assemble_blueprint
from backend.onboarding_agent.discover import discover_domain, discover_schema
from backend.onboarding_agent.draft_rbac import draft_rbac
from backend.onboarding_agent.suggest_tools import suggest_tools, suggest_tools_and_metadata

__all__ = [
    "discover_schema",
    "discover_domain",
    "suggest_tools",
    "suggest_tools_and_metadata",
    "draft_rbac",
    "assemble_blueprint",
]
