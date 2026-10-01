# LogiRush Terrain Intelligence & Multi-Hazard Engine

How LogiRush scores a corridor for **the hazards of its own terrain**, and exactly where each number comes from.

Everything here is deterministic and documented. The only machine-learning component is still the flood/landslide Random Forest (trained on synthetic data). This layer decides where that model applies and adds rule-based hazards on top of it. The rules use published thresholds wherever they exist.

---

## 1. Why one national formula is not enough

The NER prototype scored every corridor as

```
100 − (0.25·weather + 0.30·landslide + 0.20·flood + 0.15·incident + 0.10·delay)
```

That fits a Meghalaya hill road. It does not fit most of the rest of India:

| Corridor | What the single formula gets wrong |
|---|---|
| Jodhpur → Jaisalmer (Thar) | Spends 30 % of the score on landslides, which cannot happen there, and ignores the 47 °C heat that can |
| Delhi → Agra (Gangetic plain) | Has no fog term, although winter fog is the main reason these highways stop |
| Bhubaneswar → Puri (Odisha coast) | Has no wind term, so a cyclone landfall barely moves the score |
| Sonamarg → Kargil (Zojila) | Has no snow term and no idea the pass is shut every winter |

## 2. Terrain profiles (`src/terrain/profiles.py`)

Each corridor has a **primary** terrain and an optional **secondary** one. Its effective profile is a 70/30 blend of the two, so the weights still sum to 1.

| Terrain | Example corridors | Heaviest weights | Not applicable |
|---|---|---|---|
| Mountain / high altitude | Zojila, Manali–Leh, Tawang | landslide .25, snow .23 | heat |
| Hill / ghat | NH10, NH29, Shiradi, Nilgiris | landslide .30, rain .22 | heat, snow below 1,500 m |
| Floodplain | Kosi, Brahmaputra, Godavari delta | flood .36, rain .20 | (landslide ≈ 0) |
| Coastal | Odisha, Konkan, Kerala coasts | wind .25, flood .22 | snow |
| Arid / semi-arid | Thar, Kutch, Rayalaseema | heat .32, wind (dust) .15 | landslide, snow |
| Plains | Punjab, Haryana, western UP | heat .20, fog .15 | landslide, snow |
| Plateau | Deccan, Malwa, Chota Nagpur | heat .20, rain .18 | snow |
| Forested / remote | Bastar, Satpura, Bandipur | delay .20, rain .20 | snow |

Incident (0.15) and delay (0.10–0.20) are always scored. The **hill** profile deliberately stays close to the original SIH formula, which was written for that terrain. Across the 32 NER corridors the mean score change is −3.8 points.

Each profile also carries:
- **Relevance** (0–1) per hazard, used by the disruption index. 0 means *not applicable*, which is different from zero risk.
- **Heat thresholds** (onset / heatwave / severe) following IMD's regional criteria.
- **Flood mechanism**: riverine, flash, coastal surge or minimal.
- **Reliability penalty** for sparse alternate roads and long service gaps.
- **Reporting coverage**. "Sparse" means that no reports is weak evidence that the road is clear.

## 3. Hazard assessors (`src/terrain/hazards.py`)

| Hazard | Input (live from Open-Meteo, or snapshot) | Rule | Threshold source |
|---|---|---|---|
| Rain | 24 h observed, 48 h forecast | IMD rainfall bands → 5 / 20 / 40 / 65 / 85 / 100, plus up to +20 for the forecast | **IMD** rainfall classification |
| Flood | rain + RF flood probability | riverine: 72 h accumulation × river-distance exposure · flash: 24 h intensity (a far lower ladder on arid ground) · coastal: flash or storm surge coupled to cyclonic wind within 10 km of the shore · the higher of the rule and (50 % baseline + 50 % RF) | IMD bands; exposure factors are policy |
| Landslide | RF landslide probability, slope, rain | Applies only where gradient ≥ 8° or the terrain is hill/mountain. Floor of 70 / 85 when a steep slope gets very heavy / extremely heavy rain | Rule of thumb, **not** GSI's regional thresholds |
| Heat | max temperature | ramps through the terrain's onset / heatwave / severe thresholds (plains 40/45/47 °C, coastal 37/40/42 °C, hills 30/35/38 °C) | **IMD** heatwave criteria (upper coastal steps are our extrapolation) |
| Wind | sustained wind, gusts | IMD cyclone scale on sustained wind (depression 31 km/h … super cyclonic storm 222 km/h), plus a gust ladder for high-sided trucks | **IMD** cyclone scale; gust ladder is policy |
| Snow | 72 h snowfall, min temperature | 0.5 / 5 / 15 / 30 cm → 35 / 60 / 80 / 95, plus 10 for black ice. Only above 1,500 m | Policy (BRO decides closures pass by pass) |
| Fog | minimum visibility, next 24 h | IMD classes: very dense < 50 m, dense < 200 m, moderate < 500 m, shallow < 1,000 m | **IMD** fog classification |

Missing data is reported as `no data` and dropped from the score, never counted as zero.

## 4. From hazards to decisions

**Accessibility** (`accessibility_engine.compute_terrain_accessibility`)

```
score = 100 − Σ (w_terrain[h] / Σw_applicable) · risk[h]      over applicable components
```

A **critical-hazard cap** stops an extreme event from hiding behind a small weight:
- any hazard ≥ 95 → score ≤ 15
- any hazard ≥ 85 → score ≤ 35

Two exceptions: rain caps only at the 95 tier, and fog at 45, because rain acts through flood and landslide, and fog slows traffic rather than stopping it.

**Multi-hazard disruption index** (used as the routing risk objective). This is a noisy-OR:

```
index = 100 · (1 − Π_h (1 − sensitivity_cargo[h] · relevance_terrain[h] · risk[h]/100))
```

Cargo sensitivity makes medicine (heat ×1.4) and perishables (heat ×1.6, fog ×1.2) avoid heatwave corridors that general freight would take.

**Typed closures.** A corridor is impassable for one of four stated reasons, and the UI always shows which:

| Type | Meaning |
|---|---|
| `reported_status` | road status in the data is Closed |
| `verified_incident` | a verified severity-5 blocking report (two-person rule) |
| `seasonal_typical` | inside the corridor's typical winter window (Zojila Dec–Apr, Manali–Leh Nov–May). Typical dates; BRO announces the real ones |
| `hazard_advisory` | an *estimate*: snow-bound pass, cyclone landfall zone, or probable submergence beside a river |

**Travel time** (`src/terrain/speed.py`) is built from:
- road-class speed for a laden truck (expressway 60 … high-altitude pass 24 km/h)
- a gentle ruling-gradient penalty
- altitude power loss above 3,000 m
- urban-approach allowance at metros
- live slowdowns for fog, observed heavy rain, snow and high wind

**Restriction-aware ETA.** `schedule_eta` walks the route in order and applies routine movement windows: the Bandipur night ban (06–21), daylight-only convoys on Zojila and the Manali–Leh road (06–18), and Uttarakhand hill advisories. A vehicle does not start a restricted leg it cannot clear before closing time. Legs longer than one window are split across days.

**Routing** (`src/optimization/ner_router.py`) is the original multi-objective A\*, extended in two ways:
- The heuristic speed bound is measured from the graph itself, so A\* stays admissible now that expressways exist. A test checks A\* against Dijkstra.
- The risk objective is recomputed per cargo from each edge's per-hazard risks.

**Vehicle suitability.** 25 t multi-axle rigs are never routed over hill roads or high passes (a policy assumption). Every vehicle class still honours its own accessibility floor.

**Baseline comparison.** Every plan also returns the terrain-blind shortest-distance route over the same open network, and how much the recommendation differs from it in distance, time, peak risk and weakest link. This is the evidence that the engine changes decisions.

## 5. Simulated scenarios (`src/terrain/scenarios.py`)

`cyclone_odisha`, `heatwave_northwest`, `himalayan_snowstorm`, `bihar_floods`, `igp_fog`, `western_ghats_monsoon`, `ner_landslides`.

Each scenario overrides the weather inputs of the corridors in its zone only. Every output is labelled `simulated: true`, and the console shows a SIMULATION banner. Results as of this build:

| Scenario | Request | Effect |
|---|---|---|
| none vs `bihar_floods` | Delhi → Guwahati | NH27 through Darbhanga/Purnia is replaced by Varanasi → Gaya → Kolkata → Malda → Siliguri; 9 north-Bihar corridors get submergence advisories |
| none vs `cyclone_odisha` | Kolkata → Chennai | NH16 coastal route is replaced by an inland route via Nagpur/Hyderabad |
| January travel date | Srinagar → Leh | no road route (Zojila seasonal closure). Helicopter airlift is offered instead |
| `heatwave_northwest`, perishable cargo | Delhi → Jodhpur | cargo-adjusted risk on the Thar corridors exceeds the risk for general cargo |

These are behaviours of the rules on sample data, **not validated predictions**.

## 6. Data and honesty

| Input | Trust level | Where |
|---|---|---|
| Towns, coordinates | real, public | `data/raw/india/india_locations.csv` |
| Corridor distances, highway names | approximate | `india_road_segments.csv`. A test guards road ≥ straight line and ≤ 3.3× |
| Terrain attributes | sample (not DEM or hydrography) | same file + `ner_segment_terrain.csv` |
| National baseline susceptibility | derived from the terrain attributes | `landslide_susceptibility()`, `flood_susceptibility()` |
| RF "historical event" features on national corridors | **proxies**, not records | `_model_features()` |
| Weather | live Open-Meteo (**not IMD**) or a synthetic per-terrain snapshot | `weather_provider.py`, `TERRAIN_SNAPSHOT` |
| Weights and thresholds | expert policy; IMD where published | `profiles.py`, `hazards.py` |

To make it real, replace the terrain CSV columns with SRTM/Cartosat slope and India-WRIS river buffers, feed IMD warnings behind `get_segment_conditions()`, and calibrate the weights against NDMA/BRO/NHAI closure records. The interfaces do not change.
