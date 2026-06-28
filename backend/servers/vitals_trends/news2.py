"""NEWS2 — National Early Warning Score 2 (published NHS algorithm).

A direct, unmodified implementation of the public RCP NEWS2 scoring table (Scale 1).
Not an invented formula. Reference: Royal College of Physicians, NEWS2.

Each parameter contributes 0-3 points; the total maps to a risk band. A score of 3 in
ANY single parameter is itself an escalation trigger ("red score").
"""

from __future__ import annotations


def _score_resp_rate(v: float) -> int:
    if v <= 8:
        return 3
    if v <= 11:
        return 1
    if v <= 20:
        return 0
    if v <= 24:
        return 2
    return 3


def _score_spo2_scale1(v: float) -> int:
    if v >= 96:
        return 0
    if v >= 94:
        return 1
    if v >= 92:
        return 2
    return 3


def _score_temp(v: float) -> int:
    if v <= 35.0:
        return 3
    if v <= 36.0:
        return 1
    if v <= 38.0:
        return 0
    if v <= 39.0:
        return 1
    return 2


def _score_systolic(v: float) -> int:
    if v <= 90:
        return 3
    if v <= 100:
        return 2
    if v <= 110:
        return 1
    if v <= 219:
        return 0
    return 3


def _score_heart_rate(v: float) -> int:
    if v <= 40:
        return 3
    if v <= 50:
        return 1
    if v <= 90:
        return 0
    if v <= 110:
        return 1
    if v <= 130:
        return 2
    return 3


def _score_consciousness(alert: bool) -> int:
    return 0 if alert else 3   # ACVPU: Alert=0; Confusion/V/P/U=3


def risk_band(total: int, any_param_is_3: bool) -> str:
    """RCP escalation bands."""
    if total >= 7:
        return "high"
    if total >= 5 or any_param_is_3:
        return "medium"
    return "low"


def compute_news2(
    resp_rate: float | None = None,
    spo2: float | None = None,
    temp: float | None = None,
    systolic_bp: float | None = None,
    heart_rate: float | None = None,
    consciousness_alert: bool | None = None,
    on_supplemental_oxygen: bool = False,
) -> dict:
    """Return the NEWS2 total, per-parameter sub-scores, band, and any missing inputs.

    Missing parameters are skipped (sub-score omitted) and listed in `missing` so the
    caller knows the score is partial — honest about Synthea's sparse vitals.
    """
    scorers = {
        "resp_rate": (resp_rate, _score_resp_rate),
        "spo2": (spo2, _score_spo2_scale1),
        "temperature": (temp, _score_temp),
        "systolic_bp": (systolic_bp, _score_systolic),
        "heart_rate": (heart_rate, _score_heart_rate),
    }
    components: dict[str, int] = {}
    missing: list[str] = []
    for name, (value, fn) in scorers.items():
        if value is None:
            missing.append(name)
        else:
            components[name] = fn(value)

    if consciousness_alert is None:
        missing.append("consciousness")
    else:
        components["consciousness"] = _score_consciousness(consciousness_alert)

    if on_supplemental_oxygen:
        components["supplemental_oxygen"] = 2

    total = sum(components.values())
    any_three = any(v == 3 for v in components.values())
    return {
        "news2_score": total,
        "risk_band": risk_band(total, any_three),
        "components": components,
        "missing": missing,
    }
