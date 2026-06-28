"""Curated drug-interaction rule lookup — Codebase PRD §5.4.

check_pairs() looks up the `interaction_rules` table for any rule whose BOTH RxNorm
codes appear in the patient's active medication set (symmetric — pair order doesn't
matter). ILLUSTRATIVE only: a small open rule set, explicitly NOT a licensed clinical
drug-interaction database.
"""

from __future__ import annotations

from backend.connectors.sql_connector import SQLConnector


async def check_pairs(conn: SQLConnector, rxnorm_codes: list[str]) -> list[dict]:
    """Return interaction rules where both drugs are in `rxnorm_codes`."""
    codes = [c for c in rxnorm_codes if c]
    if len(codes) < 2:
        return []
    rows = await conn.query({"sql":
        "SELECT rxnorm_code_a, rxnorm_code_b, severity, description "
        "FROM interaction_rules "
        "WHERE rxnorm_code_a = ANY($1::text[]) AND rxnorm_code_b = ANY($1::text[])",
        "args": [codes]})
    return rows
