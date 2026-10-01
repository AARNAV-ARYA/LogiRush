# src/terrain/profiles.py
"""
Terrain profiles — the per-region "algorithm settings" of the platform.

Why profiles instead of one formula
-----------------------------------
The NER prototype scored every corridor with one formula:

    100 - (0.25*weather + 0.30*landslide + 0.20*flood + 0.15*incident + 0.10*delay)

That is a good formula for a hill road in Meghalaya and a poor one almost everywhere else. A
landslide weight of 0.30 on a Rajasthan desert highway spends a third of the score on a hazard
that physically cannot happen there, and it leaves no room for the 46 degree heat that does.
Fog, which closes the Indo-Gangetic plain's highways every winter, is not in it at all.

So each terrain class carries its own weight vector over the same components, and the
accessibility score becomes

    100 - sum_h ( w_terrain[h] * risk[h] )        (weights sum to 1, as before)

plus a critical-hazard cap (see accessibility_engine.compute_terrain_accessibility) so that a
hazard the weights consider minor for a terrain can still take the road out when it is extreme.

What the numbers are
--------------------
The weights, relevance values and thresholds below are EXPERT-ELICITED POLICY, written down
explicitly so they can be argued with. They are not fitted to outcome data (there is none in
this repository). Where a threshold comes from a published source it says so; where it is our
extrapolation it says that too. Tune them here; nothing else hard-codes them.

The hill profile deliberately stays close to the original SIH Module 1 weights (it is the
terrain that formula was written for), so the North Eastern hill corridors behave as before.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Natural hazards assessed per corridor.
HAZARDS = ("rain", "landslide", "flood", "heat", "wind", "snow", "fog")
# Operational components that are scored alongside them.
OPERATIONAL = ("incident", "delay")
COMPONENTS = HAZARDS + OPERATIONAL

HAZARD_LABELS = {
    "rain": "Heavy rainfall",
    "landslide": "Landslide",
    "flood": "Flooding / waterlogging",
    "heat": "Extreme heat",
    "wind": "Cyclone / high wind",
    "snow": "Snowfall / ice",
    "fog": "Dense fog",
    "incident": "Reported incidents",
    "delay": "Congestion / delay",
}

TERRAIN_CLASSES = (
    "mountain", "hill", "floodplain", "coastal", "arid", "plains", "plateau", "forest_remote",
)


@dataclass(frozen=True)
class TerrainProfile:
    key: str
    label: str
    description: str
    example_regions: tuple
    # Accessibility weights over COMPONENTS. Sum to 1.0.
    weights: dict
    # How much each hazard matters to *disruption* on this terrain, 0..1. 0 means the hazard is
    # not applicable at all (snow on the Konkan coast) and it is excluded, not scored as zero.
    relevance: dict
    # IMD heatwave-style thresholds for daily maximum temperature (deg C):
    # (onset, heatwave, severe heatwave).
    heat_thresholds: tuple
    # Which flood mechanism dominates: riverine (slow, multi-day accumulation), flash (short
    # intense rain on hard or dry ground), coastal (surge coupled to cyclonic wind) or
    # minimal (steep terrain drains; flooding is a secondary effect of slides).
    flood_mode: str
    # Extra 0-100 reliability penalty for the terrain itself: sparse alternate roads, long gaps
    # between fuel/repair services, slow recovery after an event.
    reliability_penalty: float
    # Multiplier on nominal road-class speed for surface/terrain effects not captured by the
    # gradient model (forest tracks, embankment diversions).
    speed_factor: float
    # How well community reporting covers this terrain. "sparse" means the absence of a report
    # is weak evidence that the road is fine, and the confidence readout says so.
    reporting_coverage: str
    considerations: tuple = field(default_factory=tuple)


def _weights(**kw) -> dict:
    out = {c: float(kw.get(c, 0.0)) for c in COMPONENTS}
    total = sum(out.values())
    if abs(total - 1.0) > 1e-6:  # pragma: no cover - guarded by tests, fail loudly at import
        raise ValueError(f"terrain weights must sum to 1.0, got {total}")
    return out


def _relevance(**kw) -> dict:
    return {h: float(kw.get(h, 0.0)) for h in HAZARDS}


PROFILES = {
    "mountain": TerrainProfile(
        key="mountain",
        label="Mountain / high altitude",
        description="Himalayan passes and high valleys above ~2,500 m.",
        example_regions=("Ladakh", "Lahaul-Spiti", "Tawang", "Zojila"),
        weights=_weights(rain=0.10, landslide=0.25, flood=0.05, wind=0.07, snow=0.23, fog=0.05,
                         incident=0.15, delay=0.10),
        relevance=_relevance(rain=0.5, landslide=1.0, flood=0.3, wind=0.6, snow=1.0, fog=0.4),
        # IMD: heatwave for hill stations when max >= 30 C with a departure of >= 5 C. Rarely
        # relevant up here, kept for completeness; relevance 0 excludes it from scoring.
        heat_thresholds=(30.0, 33.0, 36.0),
        flood_mode="minimal",
        reliability_penalty=12.0,
        speed_factor=1.0,
        reporting_coverage="sparse",
        considerations=(
            "Seasonal closure windows are hard constraints (typical dates; BRO announces actual).",
            "Snowfall and black ice dominate; driving is restricted to daylight on the passes.",
            "Engines lose power with altitude; travel time rises above 3,000 m.",
        ),
    ),
    "hill": TerrainProfile(
        key="hill",
        label="Hill / ghat",
        description="Hill roads and ghat sections: North East, Himalayan foothills, Western and "
                    "Eastern Ghats, Nilgiris.",
        example_regions=("Meghalaya", "Mizoram", "Uttarakhand", "Western Ghats", "Nilgiris"),
        weights=_weights(rain=0.22, landslide=0.30, flood=0.13, wind=0.03, snow=0.02, fog=0.05,
                         incident=0.15, delay=0.10),
        relevance=_relevance(rain=0.7, landslide=1.0, flood=0.5, heat=0.1, wind=0.3, snow=0.3,
                             fog=0.4),
        heat_thresholds=(30.0, 35.0, 38.0),
        flood_mode="minimal",
        reliability_penalty=5.0,
        speed_factor=1.0,
        reporting_coverage="moderate",
        considerations=(
            "Landslides driven by slope and saturating rain are the dominant disruption.",
            "Heavy rain is weighted high because it is the trigger, not just a nuisance.",
        ),
    ),
    "floodplain": TerrainProfile(
        key="floodplain",
        label="Floodplain / river valley",
        description="Low-lying alluvial plains beside major rivers: Brahmaputra, Kosi, Gandak, "
                    "Ganga, Godavari-Krishna deltas.",
        example_regions=("North Bihar", "Assam valley", "Eastern UP", "Godavari delta"),
        weights=_weights(rain=0.20, landslide=0.02, flood=0.36, heat=0.05, wind=0.03, fog=0.09,
                         incident=0.15, delay=0.10),
        relevance=_relevance(rain=0.6, landslide=0.1, flood=1.0, heat=0.4, wind=0.4, fog=0.8),
        # IMD plains criterion: heatwave when max >= 40 C (departure >= 4.5 C), or >= 45 C
        # outright; severe at >= 47 C.
        heat_thresholds=(40.0, 45.0, 47.0),
        flood_mode="riverine",
        reliability_penalty=4.0,
        speed_factor=0.95,
        reporting_coverage="moderate",
        considerations=(
            "Riverine flooding builds over days, so 72-hour accumulated rain drives the flood rule.",
            "Distance to the river scales exposure; embankment breaches close whole stretches.",
            "Winter fog on the Gangetic plain is a major seasonal disruption.",
        ),
    ),
    "coastal": TerrainProfile(
        key="coastal",
        label="Coastal",
        description="Corridors within a few tens of km of the sea: Odisha, Andhra, Tamil Nadu, "
                    "Konkan, Kerala, Gujarat coasts.",
        example_regions=("Odisha coast", "Konkan", "Kerala", "Coromandel coast", "Kutch coast"),
        weights=_weights(rain=0.20, landslide=0.05, flood=0.22, heat=0.03, wind=0.25,
                         incident=0.15, delay=0.10),
        relevance=_relevance(rain=0.7, landslide=0.3, flood=0.9, heat=0.3, wind=1.0, fog=0.1),
        # IMD coastal criterion: heatwave when max >= 37 C with departure >= 4.5 C. The 40 / 42
        # upper steps are our extrapolation for coastal humidity, not an IMD category.
        heat_thresholds=(37.0, 40.0, 42.0),
        flood_mode="coastal",
        reliability_penalty=3.0,
        speed_factor=1.0,
        reporting_coverage="dense",
        considerations=(
            "Cyclonic wind is scored on the IMD cyclone intensity scale.",
            "Storm surge couples flooding to wind on low-lying segments near the shore.",
        ),
    ),
    "arid": TerrainProfile(
        key="arid",
        label="Arid / semi-arid",
        description="Thar desert, Kutch, Rayalaseema: long, sparse corridors.",
        example_regions=("Western Rajasthan", "Kutch", "Rayalaseema"),
        weights=_weights(rain=0.08, flood=0.10, heat=0.32, wind=0.15, fog=0.05,
                         incident=0.15, delay=0.15),
        relevance=_relevance(rain=0.3, flood=0.6, heat=1.0, wind=0.7, fog=0.2),
        heat_thresholds=(40.0, 45.0, 47.0),
        flood_mode="flash",
        reliability_penalty=8.0,
        speed_factor=1.0,
        reporting_coverage="sparse",
        considerations=(
            "Extreme heat is the dominant hazard: tyre failures, driver fatigue, cold-chain loss.",
            "Dust storms are scored through wind gusts.",
            "Rare rain produces flash floods on dry, hard ground at far lower totals.",
            "Long gaps between services make delay costlier, so delay carries more weight.",
        ),
    ),
    "plains": TerrainProfile(
        key="plains",
        label="Plains",
        description="Indo-Gangetic and other flat agricultural plains with dense traffic.",
        example_regions=("Punjab", "Haryana", "Western UP", "Delhi NCR"),
        weights=_weights(rain=0.15, flood=0.15, heat=0.20, wind=0.05, fog=0.15,
                         incident=0.15, delay=0.15),
        relevance=_relevance(rain=0.5, flood=0.6, heat=0.8, wind=0.4, fog=1.0),
        heat_thresholds=(40.0, 45.0, 47.0),
        flood_mode="flash",
        reliability_penalty=0.0,
        speed_factor=1.0,
        reporting_coverage="dense",
        considerations=(
            "Winter fog is weighted as heavily as heat: visibility below 50 m stops convoys.",
            "Congestion matters more than terrain on these corridors.",
        ),
    ),
    "plateau": TerrainProfile(
        key="plateau",
        label="Plateau",
        description="Deccan, Malwa and Chota Nagpur plateaus.",
        example_regions=("Deccan", "Malwa", "Telangana", "Chota Nagpur"),
        weights=_weights(rain=0.18, landslide=0.04, flood=0.15, heat=0.20, wind=0.05, fog=0.08,
                         incident=0.15, delay=0.15),
        relevance=_relevance(rain=0.6, landslide=0.3, flood=0.6, heat=0.8, wind=0.4, fog=0.5),
        heat_thresholds=(40.0, 45.0, 47.0),
        flood_mode="flash",
        reliability_penalty=2.0,
        speed_factor=1.0,
        reporting_coverage="moderate",
        considerations=(
            "Pre-monsoon heat and monsoon flash flooding at river crossings.",
            "Landslide only where a ghat section is crossed (gradient-gated).",
        ),
    ),
    "forest_remote": TerrainProfile(
        key="forest_remote",
        label="Forested / remote",
        description="Forest and tribal belts with sparse roads: Bastar, Satpura, Eastern Ghats "
                    "interior, tiger-reserve corridors.",
        example_regions=("Bastar", "Satpura", "Koraput", "Bandipur-Mudumalai"),
        weights=_weights(rain=0.20, landslide=0.10, flood=0.18, heat=0.07, wind=0.05, fog=0.05,
                         incident=0.15, delay=0.20),
        relevance=_relevance(rain=0.7, landslide=0.5, flood=0.7, heat=0.4, wind=0.4, fog=0.4),
        heat_thresholds=(40.0, 45.0, 47.0),
        flood_mode="flash",
        reliability_penalty=10.0,
        speed_factor=0.9,
        reporting_coverage="sparse",
        considerations=(
            "Few alternate roads: a single blockage strands a region, so reliability is penalised.",
            "Sparse reporting — no report is weak evidence of a clear road.",
            "Some corridors ban night movement through protected areas.",
        ),
    ),
}

# Share of a mixed corridor's character taken from its secondary terrain.
SECONDARY_SHARE = 0.3


@dataclass(frozen=True)
class EffectiveProfile:
    """A corridor's working profile: its primary terrain blended with its secondary."""

    primary: str
    secondary: str | None
    weights: dict
    relevance: dict
    heat_thresholds: tuple
    flood_mode: str
    reliability_penalty: float
    speed_factor: float
    reporting_coverage: str

    @property
    def label(self) -> str:
        base = PROFILES[self.primary].label
        if self.secondary:
            return f"{base} + {PROFILES[self.secondary].label.lower()}"
        return base

    def applicable(self, hazard: str) -> bool:
        return self.relevance.get(hazard, 0.0) > 0.0


def get_profile(key: str | None) -> TerrainProfile:
    """Profile by key, defaulting to plains for anything unrecognised.

    Plains is the most neutral profile (no landslide, no snow, balanced weights), which is the
    least surprising thing to apply to a corridor whose terrain was never recorded.
    """
    return PROFILES.get((key or "").strip().lower(), PROFILES["plains"])


def effective_profile(primary: str | None, secondary: str | None = None) -> EffectiveProfile:
    """Blend a primary and optional secondary terrain.

    Weights are a convex 70/30 mix (so they still sum to 1). Relevance takes the larger of the
    primary's value and a discounted secondary value: a coastal corridor that climbs a ghat
    does face landslides, just less centrally than a hill road does. Thresholds and the flood
    mechanism follow the primary terrain, which is where most of the corridor lies.
    """
    p = get_profile(primary)
    s = PROFILES.get((secondary or "").strip().lower()) if secondary else None
    if s is None or s.key == p.key:
        return EffectiveProfile(
            primary=p.key, secondary=None, weights=dict(p.weights), relevance=dict(p.relevance),
            heat_thresholds=p.heat_thresholds, flood_mode=p.flood_mode,
            reliability_penalty=p.reliability_penalty, speed_factor=p.speed_factor,
            reporting_coverage=p.reporting_coverage,
        )

    share = SECONDARY_SHARE
    weights = {c: round((1 - share) * p.weights[c] + share * s.weights[c], 6) for c in COMPONENTS}
    relevance = {
        h: round(max(p.relevance[h], 0.6 * s.relevance[h]), 3) for h in HAZARDS
    }
    coverage_rank = {"sparse": 0, "moderate": 1, "dense": 2}
    coverage = min((p.reporting_coverage, s.reporting_coverage), key=lambda c: coverage_rank[c])
    return EffectiveProfile(
        primary=p.key,
        secondary=s.key,
        weights=weights,
        relevance=relevance,
        heat_thresholds=p.heat_thresholds,
        flood_mode=p.flood_mode,
        reliability_penalty=max(p.reliability_penalty, s.reliability_penalty),
        speed_factor=min(p.speed_factor, s.speed_factor),
        reporting_coverage=coverage,
    )


def describe_profiles() -> list:
    """The whole table, for the API — explainability is a requirement, not a nicety."""
    out = []
    for key in TERRAIN_CLASSES:
        p = PROFILES[key]
        out.append({
            "key": p.key,
            "label": p.label,
            "description": p.description,
            "example_regions": list(p.example_regions),
            "weights": p.weights,
            "relevance": p.relevance,
            "applicable_hazards": [h for h in HAZARDS if p.relevance[h] > 0],
            "heat_thresholds_c": {
                "onset": p.heat_thresholds[0],
                "heatwave": p.heat_thresholds[1],
                "severe": p.heat_thresholds[2],
            },
            "flood_mode": p.flood_mode,
            "reliability_penalty": p.reliability_penalty,
            "speed_factor": p.speed_factor,
            "reporting_coverage": p.reporting_coverage,
            "considerations": list(p.considerations),
        })
    return out
