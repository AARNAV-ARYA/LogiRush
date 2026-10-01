# src/modeling/accessibility_engine.py
"""
Accessibility Intelligence Engine (SIH Module 1).

Deterministic, rule-based scoring only — per the project's AI Usage Policy, accessibility
score calculation must NOT use ML. This module has no model, no training data, and no
dependency on the Disaster Prediction Engine (Module 2); it only combines already-known
risk inputs (weather, landslide, flood, community incidents, delay) into a single 0-100
score and a category label.

Kept isolated on purpose: the Disaster Prediction Engine (future module) may FEED this
engine a "predicted" risk number, but this engine itself stays a pure function of whatever
risk inputs it's given, so it stays auditable and independently testable.
"""

from dataclasses import dataclass

# Weights from the SIH spec's Module 1 formula:
#   AccessibilityScore = 100 - (0.25*WeatherRisk + 0.30*LandslideRisk + 0.20*FloodRisk
#                                + 0.15*IncidentRisk + 0.10*DelayRisk)
WEATHER_WEIGHT = 0.25
LANDSLIDE_WEIGHT = 0.30
FLOOD_WEIGHT = 0.20
INCIDENT_WEIGHT = 0.15
DELAY_WEIGHT = 0.10

# Category thresholds from the spec (upper bound exclusive, except the top band).
CATEGORY_BANDS = [
    (80, 100, "Excellent"),
    (60, 80, "Good"),
    (40, 60, "Moderate"),
    (20, 40, "Poor"),
    (0, 20, "Critical"),
]


@dataclass(frozen=True)
class AccessibilityResult:
    score: float
    category: str
    inputs: dict


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def categorize_accessibility(score: float) -> str:
    """Map a 0-100 accessibility score to its category label."""
    score = _clamp(score)
    for lower, upper, label in CATEGORY_BANDS:
        # Top band (80-100) is inclusive on both ends; others are [lower, upper).
        if lower == 80:
            if lower <= score <= upper:
                return label
        elif lower <= score < upper:
            return label
    return "Critical"  # score == 0 falls through here defensively


def compute_accessibility_score(
    weather_risk: float,
    landslide_risk: float,
    flood_risk: float,
    incident_risk: float,
    delay_risk: float,
) -> float:
    """
    Compute the 0-100 Accessibility Score from five 0-100 risk inputs.

    Each *_risk argument is expected on a 0-100 scale (0 = no risk, 100 = maximum risk).
    Out-of-range inputs are clamped rather than raising, since upstream data sources
    (community reports, weather feeds) cannot always be trusted to stay in-range.
    """
    weather_risk = _clamp(weather_risk)
    landslide_risk = _clamp(landslide_risk)
    flood_risk = _clamp(flood_risk)
    incident_risk = _clamp(incident_risk)
    delay_risk = _clamp(delay_risk)

    penalty = (
        WEATHER_WEIGHT * weather_risk
        + LANDSLIDE_WEIGHT * landslide_risk
        + FLOOD_WEIGHT * flood_risk
        + INCIDENT_WEIGHT * incident_risk
        + DELAY_WEIGHT * delay_risk
    )
    return round(_clamp(100 - penalty), 2)


def assess_segment(
    weather_risk: float,
    landslide_risk: float,
    flood_risk: float,
    incident_risk: float,
    delay_risk: float,
) -> AccessibilityResult:
    """Convenience wrapper returning both the score and its category together."""
    score = compute_accessibility_score(
        weather_risk, landslide_risk, flood_risk, incident_risk, delay_risk
    )
    return AccessibilityResult(
        score=score,
        category=categorize_accessibility(score),
        inputs={
            "weather_risk": weather_risk,
            "landslide_risk": landslide_risk,
            "flood_risk": flood_risk,
            "incident_risk": incident_risk,
            "delay_risk": delay_risk,
        },
    )


# ---------------------------------------------------------------- terrain-aware (Pan-India)
#
# The same idea as the SIH Module 1 formula — 100 minus a weighted sum of 0-100 risks — with
# the weights supplied by the corridor's terrain profile (src/terrain/profiles.py) instead of
# being fixed nationally. Still deterministic, still ML-free: the only ML output that can reach
# this function is a flood or landslide risk the service has already blended with baseline.

# A hazard at or above these levels caps the score regardless of its terrain weight. Weights
# tune the ordinary regime; they must not let an extreme event hide behind a small weight (a
# plains corridor under a cyclonic storm is not "Good" because plains weight wind at 0.05).
CRITICAL_HAZARD_CAPS = (
    (95.0, 15.0),  # hazard >= 95 -> score at most 15 (Critical)
    (85.0, 35.0),  # hazard >= 85 -> score at most 35 (Poor)
)

# Per-hazard exceptions to the 85 tier. Rain is a trigger whose damage already arrives through
# the flood and landslide terms, so it only caps at the extremely-heavy (95) tier. Fog stops
# nothing outright — it slows traffic, which travel time already models — so very dense fog
# caps at Moderate (45): heavy rigs are held, ordinary trucks keep moving slowly.
TIER_85_CEILING_OVERRIDE = {"rain": None, "fog": 45.0}


def compute_terrain_accessibility(risks: dict, weights: dict) -> dict:
    """Terrain-weighted accessibility score.

    `risks` maps component -> 0-100 risk, or None when the component does not apply to this
    corridor (snow on the Konkan coast) or has no data. Missing components are excluded and
    the remaining weights are renormalised, so a corridor is never rewarded for a hazard that
    was not measured — nor penalised for one that cannot happen there.

    Returns score, category, the effective weights actually used, the per-component penalty
    contributions (for the "why" panel), and which cap fired, if any.
    """
    used = {c: float(w) for c, w in weights.items() if w > 0 and risks.get(c) is not None}
    total_weight = sum(used.values())
    if total_weight <= 0:
        return {"score": 100.0, "category": categorize_accessibility(100.0), "weights_used": {},
                "contributions": {}, "cap": None}

    contributions = {
        c: round((w / total_weight) * _clamp(float(risks[c])), 2) for c, w in used.items()
    }
    score = _clamp(100.0 - sum(contributions.values()))

    cap_applied = None
    natural = [c for c in used if c not in ("incident", "delay")]
    for threshold, default_ceiling in CRITICAL_HAZARD_CAPS:
        candidates = []
        for c in natural:
            if float(risks[c]) < threshold:
                continue
            ceiling = default_ceiling
            if threshold < 95.0 and c in TIER_85_CEILING_OVERRIDE:
                ceiling = TIER_85_CEILING_OVERRIDE[c]
            if ceiling is not None:
                candidates.append((ceiling, c))
        if candidates:
            ceiling, worst_component = min(candidates)
            if score > ceiling:
                cap_applied = {"hazard": worst_component, "risk": round(float(risks[worst_component]), 1),
                               "ceiling": ceiling}
                score = ceiling
            break

    score = round(score, 2)
    return {
        "score": score,
        "category": categorize_accessibility(score),
        "weights_used": {c: round(w / total_weight, 4) for c, w in used.items()},
        "contributions": contributions,
        "cap": cap_applied,
    }
