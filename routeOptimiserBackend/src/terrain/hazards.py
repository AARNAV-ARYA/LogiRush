# src/terrain/hazards.py
"""
Multi-hazard assessment — one deterministic assessor per hazard, tuned per terrain.

Every assessor returns a `HazardAssessment` with a 0-100 risk (or None when the hazard does
not apply to this corridor), a plain-language level, and the drivers that produced it. The
only learned input anywhere in here is the flood/landslide probability from the existing
Random Forest, which the service passes in as a plain number; everything else is a published
threshold or a documented rule.

Threshold sources
-----------------
    rain       IMD 24-hour rainfall classification (light ... extremely heavy)
    heat       IMD heatwave criteria (plains >= 40 C, coastal >= 37 C, hills >= 30 C,
               heatwave at >= 45 C and severe at >= 47 C on the plains)
    wind       IMD cyclonic-disturbance intensity scale on sustained wind (depression 31-49
               km/h ... super cyclonic storm >= 222 km/h). The gust ladder for high-sided
               vehicles is our policy assumption, not an IMD product.
    fog        IMD fog classification by visibility (very dense < 50 m, dense 50-200 m,
               moderate 200-500 m, shallow 500-1000 m)
    snow       our ladder on 48-hour snowfall accumulation (no national standard exists for
               road closure; BRO decides pass by pass)
    flood      terrain-specific rules (see `assess_flood`) combined with the RF estimate
    landslide  the RF estimate, gated to slopes where landslides can occur, plus an IMD
               "very heavy rain on a steep slope" trigger. This is a rule of thumb, NOT GSI's
               regional landslide early-warning thresholds.

None of this is validated against outcome data. It is a transparent, arguable baseline that
a real deployment would calibrate against NDMA/GSI/CWC/BRO event records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.terrain.profiles import HAZARDS, EffectiveProfile


@dataclass
class HazardAssessment:
    hazard: str
    applicable: bool
    risk: Optional[float]          # 0-100, None when not applicable or no data
    level: str                     # human-readable band
    drivers: list = field(default_factory=list)
    method: str = "rule"           # rule | model+baseline | rule+model | not_applicable | no_data

    def to_dict(self) -> dict:
        return {
            "hazard": self.hazard,
            "applicable": self.applicable,
            "risk": None if self.risk is None else round(self.risk, 1),
            "level": self.level,
            "drivers": self.drivers,
            "method": self.method,
        }


def _not_applicable(hazard: str, why: str) -> HazardAssessment:
    return HazardAssessment(hazard, False, None, "not applicable", [why], "not_applicable")


def _no_data(hazard: str, what: str) -> HazardAssessment:
    return HazardAssessment(hazard, True, None, "no data", [f"{what} unavailable"], "no_data")


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(v)))


def _interp(x: float, points: list) -> float:
    """Piecewise-linear interpolation through (x, y) points, flat beyond both ends."""
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


# ---------------------------------------------------------------- rain


def imd_rain_band(mm_24h: float) -> str:
    if mm_24h < 2.5:
        return "no rain / very light"
    if mm_24h < 15.6:
        return "light"
    if mm_24h < 64.5:
        return "moderate"
    if mm_24h < 115.6:
        return "heavy"
    if mm_24h < 204.5:
        return "very heavy"
    return "extremely heavy"


def assess_rain(profile: EffectiveProfile, cond: dict) -> HazardAssessment:
    from src.data_processing.weather_provider import rainfall_to_weather_risk

    r24, r48 = cond.get("rain_24h"), cond.get("rain_48h")
    if r24 is None and r48 is None:
        return _no_data("rain", "rainfall")
    r24, r48 = float(r24 or 0.0), float(r48 or 0.0)
    risk = rainfall_to_weather_risk(r24, r48)
    return HazardAssessment(
        "rain", True, risk, imd_rain_band(r24),
        [f"{r24:.0f} mm in the last 24 h (IMD: {imd_rain_band(r24)})",
         f"{r48:.0f} mm forecast over 48 h"],
    )


# ---------------------------------------------------------------- flood

# Flash-flood ladders on 24 h rainfall. The default follows IMD's heavy / very heavy /
# extremely heavy boundaries; the arid ladder is deliberately far lower because desert ground
# sheds almost all of it (Barmer 2006 flooded on totals a Meghalaya road would not notice).
_FLASH_LADDER = {
    "default": [(0, 0), (35, 10), (64.5, 35), (115.6, 60), (204.5, 85), (300, 95)],
    "arid": [(0, 0), (10, 10), (25, 35), (50, 60), (100, 85), (150, 95)],
}
# Riverine ladder on 72 h accumulation (24 h observed + 48 h forecast): rivers respond to
# what has fallen across the catchment over days, not to one intense hour.
_RIVERINE_LADDER = [(0, 0), (25, 5), (50, 15), (100, 35), (200, 60), (300, 80), (400, 95)]


def _river_exposure(river_km: float | None) -> float:
    if river_km is None:
        return 0.6
    if river_km <= 1:
        return 1.0
    if river_km <= 3:
        return 0.9
    if river_km <= 10:
        return 0.7
    if river_km <= 50:
        return 0.5
    return 0.35


def assess_flood(
    profile: EffectiveProfile,
    cond: dict,
    attrs: dict,
    baseline: float,
    model_probability: float | None,
    wind: HazardAssessment | None = None,
) -> HazardAssessment:
    """Flood / waterlogging risk using the mechanism that dominates on this terrain.

        riverine  72 h accumulation x distance-to-river exposure       (floodplains)
        flash     24 h intensity on the terrain's own ladder           (arid, plains, plateau)
        coastal   flash ladder, or storm surge coupled to cyclonic wind (coast within 10 km)
        minimal   half the flash ladder, valley floors only            (hills, mountains)

    The Random Forest's flood probability is blended 50/50 with the corridor's baseline
    susceptibility exactly as the NER platform did, and the rule result is taken instead
    whenever it is higher: the model was trained on synthetic North Eastern ranges, and the
    physically-grounded rule is the safer floor outside them.
    """
    if not profile.applicable("flood"):
        return _not_applicable("flood", f"{profile.label}: flooding not a primary mechanism")

    r24 = float(cond.get("rain_24h") or 0.0)
    r48 = float(cond.get("rain_48h") or 0.0)
    drivers = []

    mode = profile.flood_mode
    if mode == "riverine":
        rule = _interp(r24 + r48, _RIVERINE_LADDER) * _river_exposure(attrs.get("river_proximity_km"))
        drivers.append(f"{r24 + r48:.0f} mm over 72 h on a riverine floodplain "
                       f"({attrs.get('river_proximity_km', '?')} km from the river)")
    elif mode == "coastal":
        rule = _interp(r24, _FLASH_LADDER["default"])
        coast_km = attrs.get("coast_distance_km")
        if wind is not None and wind.risk is not None and coast_km is not None and coast_km <= 10:
            surge = wind.risk * (0.9 if coast_km <= 2 else 0.7)
            if surge > rule:
                drivers.append(f"storm-surge exposure: {wind.level} winds within {coast_km} km of the coast")
                rule = surge
        drivers.append(f"{r24:.0f} mm in 24 h on a coastal corridor")
    elif mode == "minimal":
        rule = 0.5 * _interp(r24, _FLASH_LADDER["default"])
        if (attrs.get("river_proximity_km") or 99) <= 1:
            rule *= 1.3
        drivers.append(f"{r24:.0f} mm in 24 h; steep terrain drains quickly")
    else:  # flash
        ladder = _FLASH_LADDER["arid" if profile.primary == "arid" else "default"]
        rule = _interp(r24, ladder)
        drivers.append(f"{r24:.0f} mm in 24 h ({'arid flash-flood ladder' if profile.primary == 'arid' else 'IMD intensity ladder'})")

    if model_probability is not None:
        model = 0.5 * float(baseline) + 0.5 * float(model_probability) * 100.0
        method = "rule+model"
        drivers.append(f"model estimate {model_probability * 100:.0f}% blended with baseline {baseline:.0f}")
    else:
        model = float(baseline)
        method = "rule+baseline"

    risk = _clamp(max(rule, model))
    level = "severe" if risk >= 80 else "high" if risk >= 60 else "elevated" if risk >= 35 else "low"
    return HazardAssessment("flood", True, risk, level, drivers, method)


# ---------------------------------------------------------------- landslide

LANDSLIDE_MIN_GRADIENT_DEG = 8.0


def assess_landslide(
    profile: EffectiveProfile,
    cond: dict,
    attrs: dict,
    baseline: float,
    model_probability: float | None,
) -> HazardAssessment:
    """Landslide risk, only where the ground can actually slide.

    The gate is physical: a corridor needs either hill/mountain terrain or a ruling gradient of
    at least 8 degrees. Without it, the forest (trained on NER hill-country ranges) would still
    hand a Punjab expressway a non-zero landslide probability from rainfall alone, and that
    number would leak into its score. Outside the gate the hazard is reported as not
    applicable, which is different from "zero risk".
    """
    gradient = float(attrs.get("ruling_gradient_deg") or 0.0)
    hilly = profile.primary in ("hill", "mountain") or profile.secondary in ("hill", "mountain")
    if not profile.applicable("landslide") or (gradient < LANDSLIDE_MIN_GRADIENT_DEG and not hilly):
        return _not_applicable("landslide", f"ruling gradient {gradient:.0f} deg on {profile.label.lower()}")

    r24 = float(cond.get("rain_24h") or 0.0)
    drivers = [f"ruling gradient {gradient:.0f} deg"]
    if model_probability is not None:
        risk = 0.5 * float(baseline) + 0.5 * float(model_probability) * 100.0
        method = "model+baseline"
        drivers.append(f"model estimate {model_probability * 100:.0f}% blended with baseline {baseline:.0f}")
    else:
        risk = float(baseline)
        method = "baseline"

    # Rainfall trigger on steep ground: IMD "very heavy" and "extremely heavy" days are when
    # hill roads actually fail. A floor, never a reduction.
    if gradient >= 15:
        if r24 >= 204.5:
            risk = max(risk, 85.0)
            drivers.append(f"extremely heavy rain ({r24:.0f} mm) on a steep slope")
        elif r24 >= 115.6:
            risk = max(risk, 70.0)
            drivers.append(f"very heavy rain ({r24:.0f} mm) on a steep slope")

    risk = _clamp(risk)
    level = "severe" if risk >= 80 else "high" if risk >= 60 else "elevated" if risk >= 35 else "low"
    return HazardAssessment("landslide", True, risk, level, drivers, method)


# ---------------------------------------------------------------- heat


def assess_heat(profile: EffectiveProfile, cond: dict) -> HazardAssessment:
    """Heat stress on the corridor, on the terrain's own IMD-style thresholds.

    The same 41 C is a normal May afternoon in Jodhpur and a heatwave on the Konkan coast, so
    the thresholds come from the profile rather than being national. Road impact: tyre and
    brake failures, bitumen softening, driver fatigue and — for medicine and perishables —
    cold-chain loss, which is why cargo sensitivity amplifies this hazard (cargo_profiles).
    """
    if not profile.applicable("heat"):
        return _not_applicable("heat", f"{profile.label}: heat is not a road hazard here")
    tmax = cond.get("tmax_c")
    if tmax is None:
        return _no_data("heat", "temperature")
    tmax = float(tmax)
    onset, heatwave, severe = profile.heat_thresholds
    risk = _interp(tmax, [(onset - 5, 0), (onset, 20), (heatwave, 55), (severe, 80), (severe + 3, 100)])
    if tmax >= severe:
        level = "severe heatwave"
    elif tmax >= heatwave:
        level = "heatwave"
    elif tmax >= onset:
        level = "hot (above heatwave onset threshold)"
    else:
        level = "normal"
    return HazardAssessment(
        "heat", True, _clamp(risk), level,
        [f"max {tmax:.1f} C against {profile.label.lower()} thresholds {onset:.0f}/{heatwave:.0f}/{severe:.0f} C"],
    )


# ---------------------------------------------------------------- wind


def imd_cyclone_category(sustained_kmh: float) -> str:
    if sustained_kmh < 31:
        return "below depression strength"
    if sustained_kmh < 50:
        return "depression"
    if sustained_kmh < 62:
        return "deep depression"
    if sustained_kmh < 89:
        return "cyclonic storm"
    if sustained_kmh < 118:
        return "severe cyclonic storm"
    if sustained_kmh < 167:
        return "very severe cyclonic storm"
    if sustained_kmh < 222:
        return "extremely severe cyclonic storm"
    return "super cyclonic storm"


_SUSTAINED_RISK = [
    (31, 25), (50, 40), (62, 60), (89, 80), (118, 92), (167, 100),
]
_GUST_LADDER = [(0, 0), (50, 0), (70, 25), (90, 45), (120, 65), (150, 85)]


def assess_wind(profile: EffectiveProfile, cond: dict) -> HazardAssessment:
    if not profile.applicable("wind"):
        return _not_applicable("wind", f"{profile.label}: wind not scored")
    sustained, gust = cond.get("wind_kmh"), cond.get("gust_kmh")
    if sustained is None and gust is None:
        return _no_data("wind", "wind")
    sustained = float(sustained or 0.0)
    gust = float(gust or 0.0)

    sustained_risk = sustained / 31.0 * 15.0 if sustained < 31 else 0.0
    for threshold, value in _SUSTAINED_RISK:
        if sustained >= threshold:
            sustained_risk = value
    gust_risk = _interp(gust, _GUST_LADDER)

    risk = max(sustained_risk, gust_risk)
    category = imd_cyclone_category(sustained)
    drivers = [f"sustained {sustained:.0f} km/h (IMD: {category})", f"gusts {gust:.0f} km/h"]
    if profile.primary == "arid" and gust_risk >= 25:
        drivers.append("dust-storm conditions likely on an arid corridor")
    level = category if sustained >= 31 else ("strong gusts" if gust_risk >= 25 else "calm / breezy")
    return HazardAssessment("wind", True, _clamp(risk), level, drivers)


# ---------------------------------------------------------------- snow

SNOW_MIN_ELEVATION_M = 1500.0
_SNOW_LADDER = [(0, 0), (0.5, 0), (0.5001, 35), (5, 60), (15, 80), (30, 95), (60, 100)]


def assess_snow(profile: EffectiveProfile, cond: dict, attrs: dict) -> HazardAssessment:
    elevation = float(attrs.get("max_elevation_m") or 0.0)
    if not profile.applicable("snow") or elevation < SNOW_MIN_ELEVATION_M:
        return _not_applicable("snow", f"max elevation {elevation:.0f} m")
    snow = cond.get("snow_cm")
    if snow is None:
        return _no_data("snow", "snowfall")
    snow = float(snow)
    risk = _interp(snow, _SNOW_LADDER)
    drivers = [f"{snow:.1f} cm snowfall over 48 h at up to {elevation:.0f} m"]

    tmin = cond.get("tmin_c")
    wet = float(cond.get("rain_24h") or 0.0) > 0.5 or snow > 0.5
    if tmin is not None and float(tmin) <= -2.0 and wet:
        risk = min(100.0, risk + 10.0)
        drivers.append(f"black-ice conditions (min {float(tmin):.0f} C on a wet surface)")

    level = ("snow-bound" if risk >= 80 else "heavy snow" if risk >= 60
             else "snowfall" if risk >= 35 else "clear" if risk < 10 else "icy")
    return HazardAssessment("snow", True, _clamp(risk), level, drivers)


# ---------------------------------------------------------------- fog


def imd_fog_class(visibility_m: float) -> str:
    if visibility_m < 50:
        return "very dense fog"
    if visibility_m < 200:
        return "dense fog"
    if visibility_m < 500:
        return "moderate fog"
    if visibility_m < 1000:
        return "shallow fog"
    return "clear"


_FOG_LADDER = [(0, 95), (50, 85), (200, 60), (500, 30), (1000, 10), (2000, 0)]


def assess_fog(profile: EffectiveProfile, cond: dict) -> HazardAssessment:
    if not profile.applicable("fog"):
        return _not_applicable("fog", f"{profile.label}: fog not scored")
    visibility = cond.get("visibility_m")
    if visibility is None:
        return _no_data("fog", "visibility")
    visibility = float(visibility)
    risk = _interp(visibility, _FOG_LADDER)
    cls = imd_fog_class(visibility)
    return HazardAssessment("fog", True, _clamp(risk), cls,
                            [f"minimum visibility {visibility:.0f} m (IMD: {cls})"])


# ---------------------------------------------------------------- combination


def assess_all(
    profile: EffectiveProfile,
    cond: dict,
    attrs: dict,
    landslide_baseline: float,
    flood_baseline: float,
    prediction=None,
) -> dict:
    """Every hazard for one corridor, keyed by hazard name."""
    flood_p = getattr(prediction, "flood_probability", None) if prediction else None
    slide_p = getattr(prediction, "landslide_probability", None) if prediction else None

    wind = assess_wind(profile, cond)
    return {
        "rain": assess_rain(profile, cond),
        "landslide": assess_landslide(profile, cond, attrs, landslide_baseline, slide_p),
        "flood": assess_flood(profile, cond, attrs, flood_baseline, flood_p, wind=wind),
        "heat": assess_heat(profile, cond),
        "wind": wind,
        "snow": assess_snow(profile, cond, attrs),
        "fog": assess_fog(profile, cond),
    }


def _risk_of(h) -> Optional[float]:
    """Risk from either a HazardAssessment or its serialised dict (graph edges carry dicts)."""
    if h is None:
        return None
    if isinstance(h, HazardAssessment):
        return h.risk
    if isinstance(h, dict):
        return h.get("risk")
    return float(h)


def disruption_index(hazards: dict, relevance: dict, sensitivity: dict | None = None) -> float:
    """Combined 0-100 disruption index across hazards (noisy-OR).

        index = 100 * (1 - prod_h (1 - s_h * rel_h * risk_h / 100))

    Noisy-OR treats hazards as independent chances of the corridor being disrupted, so two
    moderate hazards compound and a single severe one dominates — which is how disruption
    actually behaves. `rel_h` is the terrain's relevance for the hazard; `s_h` is the cargo's
    sensitivity (e.g. perishables to heat), capped so no term exceeds certainty.

    This is an INDEX, not a calibrated probability. The field that is a (synthetic-trained)
    probability is still `prediction.combined_disruption_probability`.
    """
    sensitivity = sensitivity or {}
    survive = 1.0
    for name in HAZARDS:
        risk = _risk_of(hazards.get(name))
        if risk is None:
            continue
        p = min(1.0, float(sensitivity.get(name, 1.0)) * float(relevance.get(name, 0.0)) * float(risk) / 100.0)
        survive *= (1.0 - p)
    return round(100.0 * (1.0 - survive), 2)


def dominant_hazard(hazards: dict, relevance: dict) -> Optional[str]:
    """The hazard contributing most to disruption on this corridor right now."""
    best, best_value = None, 0.0
    for name in HAZARDS:
        h = hazards.get(name)
        if h is None or h.risk is None:
            continue
        value = h.risk * relevance.get(name, 0.0)
        if value > best_value:
            best, best_value = name, value
    # Below 25 (relevance-weighted) nothing is worth naming as "the" hazard.
    return best if best_value >= 25.0 else None


def weather_speed_factor(hazards: dict, cond: dict | None = None) -> tuple:
    """How much current conditions slow traffic, and why. Returns (factor, reasons).

    Hazards do not only threaten closure; they slow everything that keeps moving. Dense fog on
    NH19 drops convoys to walking pace, snow chains halve speed on a pass. Factors multiply,
    floored at 0.35 so a corridor that is still open is never modelled as stationary (closure
    is a separate, explicit decision).

    Rain slows traffic by what is actually falling (the observed 24 h IMD band), not by the
    forecast look-ahead that the rain *risk* includes — tomorrow's rain does not slow today.
    """
    factor, reasons = 1.0, []

    def apply(f, why):
        nonlocal factor
        factor *= f
        reasons.append(why)

    # Fog sits over the night and early morning, not the whole day, so its factor is a
    # day-averaged one: roughly half the journey at walking pace, half at normal speed.
    fog = hazards.get("fog")
    if fog and fog.risk is not None:
        if fog.risk >= 85:
            apply(0.6, "very dense fog")
        elif fog.risk >= 60:
            apply(0.75, "dense fog")
        elif fog.risk >= 30:
            apply(0.9, "moderate fog")

    observed = (cond or {}).get("rain_24h")
    if observed is not None:
        observed = float(observed)
        if observed >= 204.5:
            apply(0.6, "extremely heavy rain")
        elif observed >= 115.6:
            apply(0.75, "very heavy rain")
        elif observed >= 64.5:
            apply(0.9, "heavy rain")
    else:
        rain = hazards.get("rain")
        if rain and rain.risk is not None and rain.risk >= 85:
            apply(0.8, "very heavy rain")

    snow = hazards.get("snow")
    if snow and snow.risk is not None:
        if snow.risk >= 60:
            apply(0.5, "heavy snow")
        elif snow.risk >= 35:
            apply(0.7, "snowfall")
    wind = hazards.get("wind")
    if wind and wind.risk is not None and wind.risk >= 60:
        apply(0.8, "high wind")
    return max(0.35, round(factor, 3)), reasons
