# src/modeling/cargo_profiles.py
"""
Essential Goods Intelligence (SIH Module 4).

Deterministic lookup table — no ML, no inference. Maps a cargo type to the weight vector
the risk-aware router optimises with, implementing the spec's priority orderings:

    Medicine:   Reliability > Risk > Time > Cost
    Food:       Reliability > Time > Cost
    Relief:     Risk > Reliability > Time
    Perishable: Time > Reliability > Risk
    General:    Balanced

The five objectives below are all "lower is better" and all normalised to a 0-100 scale
before weighting (see ner_graph_builder.py), so the weights are directly comparable and
each profile's weights sum to 1.0.

Objectives:
    time          - journey duration
    cost          - monetary transport cost
    accessibility - penalty for low accessibility (100 - accessibility_score)
    risk          - predicted disruption probability (Module 2 output, as a percentage)
    reliability   - penalty for unreliable roads (status, delay factor, incident history)
"""

OBJECTIVES = ["time", "cost", "accessibility", "risk", "reliability"]

CARGO_PROFILES = {
    "medicine": {
        "label": "Medicine",
        "weights": {"reliability": 0.30, "risk": 0.25, "time": 0.20, "accessibility": 0.20, "cost": 0.05},
        "rationale": "Medical supplies must arrive intact and on schedule; cost is the least "
                     "important consideration, so reliability and risk dominate.",
    },
    "food": {
        "label": "Food",
        "weights": {"reliability": 0.30, "time": 0.25, "cost": 0.15, "risk": 0.15, "accessibility": 0.15},
        "rationale": "Food shipments prioritise dependable delivery and reasonable speed, "
                     "with cost still mattering more than for medicine.",
    },
    "relief": {
        "label": "Relief Material",
        "weights": {"risk": 0.30, "reliability": 0.25, "time": 0.20, "accessibility": 0.20, "cost": 0.05},
        "rationale": "Relief convoys move during active disruption, so avoiding risky corridors "
                     "outranks everything; cost is near-irrelevant in an emergency.",
    },
    "perishable": {
        "label": "Perishable Agricultural Goods",
        "weights": {"time": 0.40, "reliability": 0.20, "risk": 0.15, "accessibility": 0.15, "cost": 0.10},
        "rationale": "Perishables spoil, so transit time dominates; a slightly riskier but "
                     "much faster corridor is usually the better trade.",
    },
    "general": {
        "label": "General",
        "weights": {"time": 0.20, "cost": 0.20, "accessibility": 0.20, "risk": 0.20, "reliability": 0.20},
        "rationale": "No special handling requirement; all five objectives weighted equally.",
    },
}

DEFAULT_CARGO_TYPE = "general"

# Urgency multiplies the time weight, then everything is re-normalised to sum to 1.
URGENCY_TIME_MULTIPLIER = {
    "low": 0.6,
    "normal": 1.0,
    "high": 1.6,
    "critical": 2.4,
}
DEFAULT_URGENCY = "normal"


def list_cargo_types() -> list:
    return [
        {"id": key, "label": profile["label"], "rationale": profile["rationale"]}
        for key, profile in CARGO_PROFILES.items()
    ]


def get_profile(cargo_type: str) -> dict:
    """Return the profile for a cargo type, falling back to 'general' for unknown values."""
    key = (cargo_type or DEFAULT_CARGO_TYPE).strip().lower()
    return CARGO_PROFILES.get(key, CARGO_PROFILES[DEFAULT_CARGO_TYPE])


def get_weights(cargo_type: str, urgency: str = DEFAULT_URGENCY) -> dict:
    """Return normalised objective weights for a cargo type at a given urgency.

    Urgency scales the time weight up or down and everything is renormalised, so a
    'critical' medicine run still respects medicine's reliability-first ordering but leans
    harder on speed than a 'low' urgency one.
    """
    weights = dict(get_profile(cargo_type)["weights"])
    multiplier = URGENCY_TIME_MULTIPLIER.get((urgency or DEFAULT_URGENCY).strip().lower(), 1.0)
    weights["time"] = weights["time"] * multiplier

    total = sum(weights.values())
    if total <= 0:
        return {obj: 1.0 / len(OBJECTIVES) for obj in OBJECTIVES}
    return {obj: round(weights.get(obj, 0.0) / total, 4) for obj in OBJECTIVES}


def describe_priority_order(cargo_type: str, urgency: str = DEFAULT_URGENCY) -> list:
    """Objectives ordered by weight, highest first — used in route explanations."""
    weights = get_weights(cargo_type, urgency)
    return [name for name, _ in sorted(weights.items(), key=lambda kv: kv[1], reverse=True)]
