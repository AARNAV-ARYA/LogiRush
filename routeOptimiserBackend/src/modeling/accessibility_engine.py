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
