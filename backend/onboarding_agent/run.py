"""
backend/onboarding_agent/run.py

Orchestrator - ties discover -> suggest -> draft_rbac -> assemble into the
one pipeline described in ONBOARDING_AGENT.md:

    pick a domain -> discover schema -> suggest tools (LLM) -> draft RBAC
                   -> write blueprint.yaml -> human approves

One process, internal stages, NOT four separate deployed agents
(PRD Person B section 5.4: "One process, internal stages - not 4 separate
deployed agents"). Output is a YAML file only - this never deploys
anything, never touches Kong or the registry.

Non-interactive - no approval prompt. Use main.py for the interactive
approve/modify/reject loop. This script is for scripting/CI/golden-file
regeneration against the 4 known domains.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from backend.onboarding_agent.assemble_blueprint import assemble_blueprint
from backend.onboarding_agent.discover import discover_domain
from backend.onboarding_agent.draft_rbac import draft_rbac
from backend.onboarding_agent.suggest_tools import suggest_tools_and_metadata

logging.basicConfig(level=logging.INFO, format="[onboarding-agent] %(message)s")
logger = logging.getLogger(__name__)

KNOWN_DOMAINS = (
    "vitals_trends",
    "labs_diagnoses",
    "medications_interactions",
    "clinical_notes_search",
)


async def onboard_domain(domain: str, output_dir: str | Path = "backend/onboarding_agent/output") -> Path:
    """
    Run the full 4-stage pipeline for one domain and return the path to the
    written blueprint.yaml.
    """
    logger.info("Stage 1/4 — discover: %s", domain)
    schema = await discover_domain(domain)

    logger.info("Stage 2/4 — suggest_tools: %s", domain)
    tools, metadata = suggest_tools_and_metadata(domain, schema)

    logger.info("Stage 3/4 — draft_rbac: %s", domain)
    rbac = draft_rbac(domain, tools)

    logger.info("Stage 4/4 — assemble_blueprint: %s", domain)
    path = assemble_blueprint(
        domain, schema, tools, rbac,
        output_dir=output_dir,
        inferred_metadata=metadata,
    )

    logger.info("Done — %s ready for human approval at %s", domain, path)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Onboarding agent — discover -> suggest -> draft RBAC -> assemble blueprint"
    )
    parser.add_argument(
        "domain",
        choices=KNOWN_DOMAINS,
        help="Which domain to onboard (must already have data stores running)",
    )
    parser.add_argument(
        "--output-dir",
        default="backend/onboarding_agent/output",
        help="Where to write <domain>.blueprint.yaml",
    )
    args = parser.parse_args()

    asyncio.run(onboard_domain(args.domain, args.output_dir))


if __name__ == "__main__":
    main()
