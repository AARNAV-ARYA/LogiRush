"""Terrain Intelligence Layer — Pan-India.

Everything that makes LogiRush treat a Himalayan pass differently from a Bihar floodplain or
a Thar desert highway lives in this package, and all of it is deterministic, documented rule
logic (no ML), so a judge or an operator can follow exactly why a corridor scored the way it
did:

    profiles.py    what each terrain class cares about: hazard weights, relevance, thresholds
    hazards.py     one assessor per hazard (rain, flood, landslide, heat, wind, snow, fog)
    speed.py       terrain-aware travel time and the night-restriction aware ETA schedule
    seasonal.py    typical seasonal closure windows (Zojila, Manali-Leh)
    scenarios.py   clearly labelled SIMULATED disruptions for demonstration and testing

The ML component (the flood/landslide Random Forest in modeling/disaster_prediction.py) is
still the only learned model. This layer decides *where it is relevant* and combines it with
the rule-based hazards that have published thresholds.
"""
