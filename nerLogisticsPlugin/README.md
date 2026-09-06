# NER Smart Logistics — plugin

Exposes the NER Smart Logistics routing engine as MCP tools, so the algorithm can be used
from Claude, Cowork, or any MCP client — not only from this project's own web console.

## What it gives you

| Tool | Purpose |
|---|---|
| `plan_route` | Risk-aware multi-objective routing. Balances time, cost, accessibility, disruption risk and reliability, reweighted by cargo type, urgency and weight. |
| `search_places` | Place name → corridor node id, plus real nearby places from OpenStreetMap. |
| `nearby_handover_points` | Where cargo can actually change hands: post offices, courier counters, depots, bus and rail stations, with phone numbers where OSM records them. |
| `corridor_status` | Which roads are degraded or closed, worst first, filterable by state. |
| `network_overview` | Region-wide situational summary. |
| `report_incident` | File a field report of a blockage. |
| `cargo_profiles` | How each cargo type reweights the objectives. |

It also installs a skill, **plan-consignment**, which teaches the assistant the right order to
call these in and how to read the numbers honestly.

## Requirements

The plugin is a thin client. It needs the NER backend running:

```bash
cd routeOptimiserBackend
pip install -r requirements.txt
python main.py            # http://localhost:5001
```

No Python packages are needed for the plugin itself — the MCP server uses only the standard
library, so there is nothing to install and nothing to break.

## Configuration

`NER_API_BASE_URL` (default `http://localhost:5001`) points at the backend. Set it to a
deployed instance to share one engine across a team:

```json
{ "mcpServers": { "ner-logistics": { "env": { "NER_API_BASE_URL": "https://your-backend.example" } } } }
```

`NER_API_TOKEN` is optional. Reporting works anonymously; a token attaches the report to a
named account so a verifier can follow it up. Verification, resolution and deletion are
deliberately **not** exposed as tools — those are human decisions gated by role and
jurisdiction, and closing a road needs two different verifiers agreeing in the review queue.

## Try it

> "I need to move 4 tonnes of relief supplies from Guwahati to Silchar — what's the safest
> route, and where do I hand it over?"

> "Which corridors in Manipur are blocked right now?"

## Data provenance

The road network is sample data: real town names, real coordinates, real highway corridor
names, hand-built rather than an official dataset. Risk figures and disruption probabilities
are model estimates from a Random Forest trained on **synthetic** data — the pipeline is
genuine, the probabilities are not validated forecasts. Place and contact data comes from
OpenStreetMap (ODbL) and is passed through exactly as recorded; a missing phone number means
OSM has none, never that one was invented.

Nothing from this plugin should be presented as official government data.
