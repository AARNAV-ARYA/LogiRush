# Pan-India Upgrade — Change Report

This report covers the upgrade that took LogiRush from a North-East-only prototype to a Pan-India, terrain-aware, multi-hazard platform. It follows the "expected output" format in the project brief. The methodology is in [TERRAIN_ENGINE.md](TERRAIN_ENGINE.md).

## Summary

- **Network**: 126 towns (the 27 NER nodes plus 99 national ones) and 178 corridors (the 32 NER corridors plus 146 national ones). That is about 36,000 km across 32 states and UTs, in a single connected graph. Every mainland state or UT capital is covered, or the hub next to it.
- **Terrain intelligence**: each corridor carries a terrain class, road class, gradient, elevation, river and coast distance, seasonal closure window and night-movement window. Eight terrain profiles decide which hazards apply and how much each one weighs.
- **Multi-hazard engine**: rain, flood, landslide, heat, cyclone/wind, snow and fog, using IMD thresholds where they exist. The existing Random Forest still produces the flood/landslide probability, but it is applied only where the terrain makes those hazards possible.
- **Routing**: travel time is terrain- and condition-aware, and the ETA includes night halts. Seasonal and hazard closures are typed. The A\* heuristic stays admissible on expressways. Risk is weighted per cargo, heavy rigs are kept off ghats, and every plan includes a baseline comparison.
- **Scenarios**: seven clearly labelled simulated events for demonstration and controlled testing.
- **Clients**: the web console now has an India-wide map, region and terrain filters, colour-by-hazard, a scenario and month selector, and a terrain/hazard/schedule/baseline panel in the planner. The dashboard compares by terrain, region or state and has a Hazard Watch. The field app has six new incident types.
- **Compatibility**: `/api/ner/*` is unchanged and the same API is also served at `/api/india/*`. `LOGIRUSH_NETWORK=ner` restores the original network exactly.

## Files

**New**
- `routeOptimiserBackend/src/terrain/` — `profiles.py`, `hazards.py`, `speed.py`, `seasonal.py`, `scenarios.py`
- `routeOptimiserBackend/src/data_processing/india_data_provider.py` — Pan-India provider, with a live-weather variant
- `routeOptimiserBackend/src/modeling/incident_types.py` — the single incident taxonomy
- `routeOptimiserBackend/data/raw/india/` — `india_locations.csv`, `india_road_segments.csv`, `ner_segment_terrain.csv`
- `routeOptimiserBackend/tests/test_pan_india.py` — 52 tests
- `TERRAIN_ENGINE.md`, `PAN_INDIA_UPGRADE.md`

**Changed (backend)**
- `weather_provider.py`: fetches temperature, wind, gusts, snowfall and visibility as well as rain; chunked and concurrent requests; a cache that knows which points it covers
- `accessibility_service.py`: adds the terrain-aware assessment path, typed closures and the `LOGIRUSH_NETWORK` switch
- `accessibility_engine.py`: adds `compute_terrain_accessibility` with the critical-hazard cap. The original formula is untouched.
- `ner_graph_builder.py`: terrain and hazard attributes on edges; uncapped additive time on the national graph
- `ner_router.py`: graph-measured admissible heuristic, cargo hazard sensitivity, terrain summary, schedule-aware ETA, terrain-aware explanations
- `routing_service.py`: per-scenario and per-month cache, `travel_date` and `scenario` on plans, non-road options when roads are closed, closures by type, baseline comparison
- `transport_modes.py` / `transport_planner.py`: national railheads, airports and waterways (NW1 and NW2 are not interconnected); vehicle terrain exclusions
- `cargo_profiles.py`: hazard sensitivity per cargo type
- `ner_routes.py` / `main.py`: `/api/india` alias; `/network`, `/terrain-profiles`, `/scenarios`, `/incident-types`; `?scenario=` and `?month=` on reads
- `data_sources.py`: provenance entries for every new input
- `places_service.py`: place search covers the whole of India
- `db/models.py`, `db/roster.py`: shared incident taxonomy; five regional demo verifiers
- `shipment_routes.py`: accepts `travel_date`
- `data/raw/ner/ner_road_segments.csv`: **four distance corrections** (RS006, RS007, RS028 were shorter than the straight line between their towns, and RS018 was twice the real distance). Noted in the file header.

**Changed (clients and plugin)**
- Web: `RouteMap.jsx`, `AccessibilityMap.jsx`, `ShipmentPlanner.jsx`, `Dashboard.jsx`, `lib/accessibility.js`, `api/client.js`, `ReportIncident.jsx`, `Incidents.jsx`, `IncidentLocationPreview.jsx`, branding in `Home`, `About`, `Contact`, `DataSources`, `AppShell`, `index.html` and the manifest
- Field app: `src/lib/theme.js` (incident types), `app.json` display name, README. The slug and URL scheme are unchanged.
- MCP plugin: `travel_date` and `scenario` on `plan_route`; cargo enum fixed to match the backend

**Tests updated** (the network grew, so the fixtures had to follow it; the behaviour they check is unchanged)
- `test_incident_impact.py`, `test_api_incidents.py`: the "off-network" examples moved from Mumbai (now on the network) to Port Blair and the open sea. The NER-only version of the test is kept.
- `test_api_transport_options.py`: the "vehicle classes take different routes" check now uses Siliguri → Kohima. Silchar–Aizawl now scores just above the truck floor, so every vehicle class shares it.
- `test_api_shipments.py`: the replan test now places its blocking incident on whichever corridor the planner chose, instead of at hard-coded coordinates.

## Design decisions and assumptions

1. **Rules, not new ML models, for the new hazards.** Heat, wind, fog and snow have published thresholds (IMD), and there is no labelled outcome data to train on. Adding synthetic-trained forests for them would look more "AI" but would be less defensible.
2. **Derived baselines rather than hand-typed ones.** The 146 national corridors get their landslide and flood susceptibility from documented formulas over their terrain attributes, not from invented numbers.
3. **"Not applicable" is not zero.** Hazards that cannot occur on a terrain are excluded, and the remaining weights are renormalised.
4. **Closures are typed.** An estimate (`hazard_advisory`) or a typical seasonal window can never be shown as a reported closure.
5. **Backward compatibility first.** The NER API paths, response fields, IDs and the original scoring function are all kept. New fields are only added.

## Tests run and results

The sandbox could not install SQLAlchemy (the package index was blocked). Database-backed tests were therefore run against a stubbed session. Results, compared with the unmodified upload under the same conditions:

| | Original upload | After upgrade |
|---|---|---|
| Passed | 143 | **196** |
| Failed or errored (all need a real database) | 43 | 43 — the **identical** test IDs |

- The 43 database-dependent tests (incident writes, shipments, audit, auth flows) could not run here. Their routing behaviour was reproduced by injecting incidents directly, and passed: RS013 closure without closing neighbours, unverified reports never closing a road, distant attributions ignored, and replan rerouting in both directions. **Run `python -m pytest` in an environment with the requirements installed before merging.**
- An API smoke test (Flask test client) passed for every new and existing read endpoint on both `/api/ner` and `/api/india`, and for scenario, month, travel-date and validation errors.
- Web console: every edited file passes a JSX syntax and undefined-name check (`tsc`). **A full `npm run build` was not possible here**: the zip's `node_modules` holds macOS-only esbuild/rollup binaries and the npm registry was blocked. Run `npm ci && npm run build` locally.
- Field app: a data-only change, not built.

## Limitations and remaining work

- Terrain attributes, distances and closure windows are sample values. Replace them with DEM, hydrography, NHAI geometry and BRO notices for any operational use.
- The Random Forest is still synthetic-trained. On high-altitude corridors it runs outside its training range (the API flags this as `out_of_training_domain`).
- Weights and thresholds are expert policy and have not been calibrated. No accuracy claim is made.
- Rail and waterway risk are still constants: a flood does not yet affect the railway.
- Island territories and roads below the backbone are not covered.
- Existing deployments only get the new regional verifier accounts when `python seed_users.py` is run.

## Configuration and deployment

- No new required environment variables. The optional `LOGIRUSH_NETWORK=ner` restores the original network.
- Live weather uses the same `NER_LIVE_WEATHER` switch. The first live fetch now makes about 4 concurrent Open-Meteo requests (around 400 sample points).
- After deploying the backend, run `python seed_users.py` to add the regional demo verifiers to an existing database.
