"""
backend/onboarding_agent/main.py

Interactive onboarding CLI - closes the loop the Codebase PRD's Phase 1
diagram describes:

    1. Onboarding (User) picks a domain
    2. Onboarding Agent proposes (discover -> suggest -> draft RBAC -> blueprint)
    3. Human Approver signs off
         Approve     -> continue (write final blueprint.yaml)
         Reject      -> revise (back to 2, with feedback)
    4. (out of this script's scope) System builds, hardens, deploys

Person B PRD section 5.4: "Human Approver reviews the blueprint file
directly - no UI required for this PRD's scope." This CLI is exactly that
file-review step, made interactive instead of "open the YAML in an editor" -
no web UI, no CopilotKit, just a terminal loop. ApprovalCard.tsx (the
CopilotKit frontend component) is a separate, optional enhancement on the
chat page (section 5.6) - this script does not depend on it and is not
replaced by it.

For domains outside the frozen 4, storage/fhir_resource/terminology are
LLM-inferred (suggest_tools.suggest_tools_and_metadata()) rather than
looked up from a static table - shown in the CLI alongside tools/RBAC so
the human approver reviews ALL inferred fields, not just tools and RBAC.

Usage:
    uv run python -m backend.onboarding_agent.main vitals_trends
    uv run python -m backend.onboarding_agent.main radiology_reports   # new domain
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from backend.onboarding_agent.assemble_blueprint import assemble_blueprint
from backend.onboarding_agent.discover import UnknownDomainError, discover_domain
from backend.onboarding_agent.draft_rbac import (
    VALID_ACCESS_LEVELS,
    apply_rbac_override,
    draft_rbac,
)
from backend.onboarding_agent.suggest_tools import suggest_tools_and_metadata

logging.basicConfig(level=logging.WARNING)  # keep the CLI output clean; details via --verbose
logger = logging.getLogger(__name__)

KNOWN_DOMAINS = {
    "vitals_trends",
    "labs_diagnoses",
    "medications_interactions",
    "clinical_notes_search",
}


def _print_header(text: str) -> None:
    print(f"\n{text}")
    print("-" * len(text))


def _print_tools(tools: list[dict]) -> None:
    _print_header("Suggested Tools")
    for i, tool in enumerate(tools, start=1):
        print(f"{i}. {tool['name']}")


def _print_rbac(rbac: dict) -> None:
    _print_header("Suggested RBAC")
    label_map = {
        "clinical-viewer": "Clinical Viewer",
        "physician": "Physician",
        "case-manager": "Case Manager",
    }
    level_map = {"allow": "Allow", "deny": "Deny", "limited": "Limited"}
    for role_key, label in label_map.items():
        level = rbac["rbac"].get(role_key, "deny")
        print(f"{label:<18}: {level_map.get(level, level)}")


def _print_metadata(domain: str, metadata: dict | None) -> None:
    """
    Only shown for domains NOT in the frozen 4 - the human approver needs to
    see and confirm storage/fhir_resource/terminology since those are
    LLM-inferred guesses, not a fixed contract.
    """
    if domain in KNOWN_DOMAINS:
        return
    _print_header("Inferred Metadata (new domain — please verify)")
    print(f"Storage       : {(metadata or {}).get('storage') or 'unknown'}")
    print(f"FHIR Resource : {(metadata or {}).get('fhir_resource') or 'unknown'}")
    print(f"Terminology   : {(metadata or {}).get('terminology') or 'none'}")


def _print_fhir_shape(domain: str, schema: dict) -> None:
    """
    Shows discover.py's heuristic FHIR field mapping - "schema (FHIR shape,
    not just SQL columns)" per Person B PRD section 5.4. Only shown for new
    domains; the frozen 4's FHIR shape is already fixed in blueprint.yaml.
    """
    if domain in KNOWN_DOMAINS:
        return
    fhir_shape = schema.get("fhir_shape") if isinstance(schema, dict) else None
    if not fhir_shape:
        return
    _print_header("Discovered FHIR Shape (heuristic — confirmed/corrected by LLM next)")
    for table_or_collection, shape in fhir_shape.items():
        if not isinstance(shape, dict):
            continue
        resource = shape.get("likely_resource_type") or "unknown"
        print(f"  {table_or_collection} -> likely resourceType: {resource}")
        for column, fhir_field in shape.get("field_mapping", {}).items():
            arrow = f"-> {fhir_field}" if fhir_field else "-> (no FHIR mapping guessed)"
            print(f"    {column:<20} {arrow}")


def _menu() -> str:
    print()
    print("Approve blueprint?")
    print("0 - Approve")
    print("1 - Modify Tools")
    print("2 - Modify RBAC")
    print("3 - Cancel")
    return input("> ").strip()


def _modify_tools_prompt() -> str:
    print("\nWhat is wrong with the current tools? (this feedback goes back to the LLM)")
    return input("Feedback: ").strip()


def _modify_rbac_prompt(rbac: dict) -> dict:
    """
    Per-role override prompt. Re-asks the SAME field on an invalid value
    instead of crashing the whole CLI session and losing all progress
    (schema, tools, prior approvals) - a typo here should cost one retry,
    not the entire onboarding run.
    """
    role_keys = ["clinical-viewer", "physician", "case-manager"]
    label_map = {
        "clinical-viewer": "Clinical Viewer",
        "physician": "Physician",
        "case-manager": "Case Manager",
    }
    print(f"\nValid levels: {', '.join(VALID_ACCESS_LEVELS)}")
    for role_key in role_keys:
        current = rbac["rbac"].get(role_key, "deny")
        while True:
            raw = input(f"{label_map[role_key]} [{current}]: ").strip()
            if not raw or raw == current:
                break  # keep current value
            try:
                rbac = apply_rbac_override(rbac, role_key, raw)
                break
            except ValueError as exc:
                print(f"  {exc} — try again.")
    return rbac


async def run_onboarding_cli(
    domain: str,
    output_dir: str | Path = "backend/onboarding_agent/output",
) -> Path | None:
    """
    Runs the interactive discover -> suggest -> draft RBAC -> approve loop.
    Returns the path to the final approved blueprint, or None if cancelled.
    """
    print("Connecting to database...")
    try:
        schema = await discover_domain(domain)
    except UnknownDomainError as exc:
        print(f"\n✗ {exc}")
        print("\nTip: known domains right now are vitals_trends, labs_diagnoses, "
              "medications_interactions, clinical_notes_search — or any domain "
              "you've already registered in egress_guard.py.")
        return None
    print(u"\u2713 Schema discovered")

    tools, metadata = suggest_tools_and_metadata(domain, schema)
    rbac = draft_rbac(domain, tools)

    while True:
        _print_fhir_shape(domain, schema)
        _print_metadata(domain, metadata)
        _print_tools(tools)
        _print_rbac(rbac)

        choice = _menu()

        if choice == "0":
            path = assemble_blueprint(
                domain, schema, tools, rbac,
                output_dir=output_dir,
                inferred_metadata=metadata,
            )
            print(f"\nApproved. Blueprint written to: {path}")
            print("Next: hand off to the hardened template build step (Person A's pipeline).")
            return path

        elif choice == "1":
            feedback = _modify_tools_prompt()
            if feedback:
                print("\nRegenerating tools with your feedback...")
                tools, metadata = suggest_tools_and_metadata(
                    domain, schema, feedback=feedback, previous_tools=tools
                )
                # Tool names changed - tool_scopes in rbac must be rebuilt
                rbac = draft_rbac(domain, tools, role_matrix={domain: rbac["rbac"]})

        elif choice == "2":
            rbac = _modify_rbac_prompt(rbac)

        elif choice == "3":
            print("\nCancelled. No blueprint written.")
            return None

        else:
            print("Invalid choice — enter 0, 1, 2, or 3.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interactive onboarding agent - discover, suggest, draft RBAC, approve."
    )
    parser.add_argument(
        "domain",
        help=(
            "Domain to onboard. One of the 4 known domains "
            "(vitals_trends, labs_diagnoses, medications_interactions, "
            "clinical_notes_search) or a new domain name."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="backend/onboarding_agent/output",
        help="Where to write the approved blueprint.yaml",
    )
    args = parser.parse_args()

    asyncio.run(run_onboarding_cli(args.domain, args.output_dir))


if __name__ == "__main__":
    main()
