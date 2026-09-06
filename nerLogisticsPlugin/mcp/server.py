#!/usr/bin/env python3
"""MCP server exposing the NER Smart Logistics routing engine.

Written against the Python standard library only, deliberately. A plugin whose first
instruction is "pip install something" is a plugin most people never get working, and the
whole point of publishing the engine is that somebody else can use it. MCP's stdio transport
is newline-delimited JSON-RPC 2.0, which needs no framework to speak correctly.

The server is a thin, honest wrapper: it calls the Flask API and returns what the engine
says. It does no routing arithmetic of its own, so there is no second implementation to drift
out of step with the real one — if a tool here disagrees with the web console, that is a bug
in the API, not in two copies of a rule.

Configure with NER_API_BASE_URL (default http://localhost:5001).
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API_BASE = os.environ.get("NER_API_BASE_URL", "http://localhost:5001").rstrip("/")
TIMEOUT_S = float(os.environ.get("NER_API_TIMEOUT_S", "20"))
PROTOCOL_FALLBACK = "2024-11-05"

SERVER_INFO = {"name": "ner-logistics", "version": "1.0.0"}


# ---------------------------------------------------------------- HTTP

def _call_api(path, method="GET", body=None):
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    token = os.environ.get("NER_API_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.loads(response.read() or "{}")
    except urllib.error.HTTPError as e:
        detail = {}
        try:
            detail = json.loads(e.read() or "{}")
        except Exception:
            pass
        raise RuntimeError(detail.get("message") or f"API returned {e.code}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Could not reach the NER backend at {API_BASE} ({e.reason}). "
            "Start it with `python main.py` in routeOptimiserBackend, or set NER_API_BASE_URL "
            "to a deployed instance."
        ) from e


def _qs(**params):
    clean = {k: v for k, v in params.items() if v is not None}
    return ("?" + urllib.parse.urlencode(clean)) if clean else ""


# ---------------------------------------------------------------- formatting
#
# Tools return prose rather than raw JSON. A model reading "Guwahati -> Silchar, 12.7 h, worst
# link 41/100 (Poor)" can reason about it and pass it on; a model handed 4 kB of nested JSON
# spends its budget parsing and frequently reports a number from the wrong field.

def _fmt_route(route, index=None):
    head = f"{'Recommended' if index == 0 else f'Alternative {index}'}: " if index is not None else ""
    cost = route.get("estimated_cost_inr")
    metrics = f"  ETA {route.get('eta_hours')} h · {round(route.get('total_distance_km', 0))} km"
    if cost is not None:
        metrics += f" · ₹{round(cost):,}"
    lines = [
        f"{head}{' -> '.join(route.get('path_names', []))}",
        metrics,
        f"  Worst link {round(route.get('worst_segment_accessibility', 0))}/100 · "
        f"peak disruption risk {round(route.get('peak_segment_risk_percent', 0))}%",
    ]
    explanation = route.get("explanation") or {}
    for reason in explanation.get("reasons", [])[:4]:
        lines.append(f"  - {reason}")
    if explanation.get("caveat"):
        lines.append(f"  Caveat: {explanation['caveat']}")
    return "\n".join(lines)


DISCLAIMER = (
    "\n\nSource: NER Smart Logistics. Road network is sample data; risk figures and disruption "
    "probabilities are model estimates from synthetic training data, not official IMD/GSI/CWC "
    "forecasts. Do not present these as government figures."
)


# ---------------------------------------------------------------- tools

def tool_plan_route(args):
    payload = {
        "origin": args["origin"],
        "destination": args["destination"],
        "cargo_type": args.get("cargo_type", "general"),
        "urgency": args.get("urgency", "normal"),
        "weight_kg": args.get("weight_kg", 1000),
    }
    result = _call_api("/api/ner/plan-route", "POST", payload)
    routes = result.get("routes") or []
    if not routes:
        return (
            f"No route available from {payload['origin']} to {payload['destination']}.\n"
            f"{result.get('message', '')}\n"
            f"Impassable corridors excluded: {', '.join(result.get('impassable_segments') or []) or 'none'}"
            + DISCLAIMER
        )
    out = [
        f"Planned {payload['cargo_type']} cargo, {payload['urgency']} urgency, "
        f"{payload['weight_kg']} kg."
    ]
    out += [_fmt_route(route, i) for i, route in enumerate(routes[:3])]
    if result.get("recommended_transport"):
        out.append(f"\nRecommended transport mode: {result['recommended_transport']}")
    return "\n\n".join(out) + DISCLAIMER


def tool_search_places(args):
    result = _call_api("/api/ner/places/search" + _qs(q=args["query"], limit=args.get("limit", 8)))
    results = result.get("results") or []
    if not results:
        return f"No places found for {args['query']!r}."
    lines = []
    for place in results:
        tag = "routable corridor node" if place.get("routable") else "nearby place (off-network)"
        lines.append(
            f"- {place['label']} [{tag}] "
            f"({place['latitude']:.4f}, {place['longitude']:.4f})"
            + (f" · id {place['location_id']}" if place.get("location_id") else "")
        )
    note = ""
    if result.get("degraded"):
        note = "\n\nNote: the external place-search service was unreachable; only corridor network nodes are listed."
    return "\n".join(lines) + note


def tool_nearby_handover_points(args):
    result = _call_api("/api/ner/places/nearby" + _qs(
        lat=args["latitude"], lon=args["longitude"], radius_km=args.get("radius_km", 5)))
    facilities = result.get("facilities") or []
    lines = []
    if facilities:
        lines.append("Handover points nearby:")
        for f in facilities[:12]:
            contact = f["phone"] if f.get("phone") else "no number listed in OpenStreetMap"
            hours = f" · {f['opening_hours']}" if f.get("opening_hours") else ""
            lines.append(f"- {f['name']} ({f['kind']}, {f['distance_km']} km) · {contact}{hours}")
        lines.append("\nPlaces and contact details from OpenStreetMap (ODbL), shown exactly as "
                     "recorded there. A missing number means OSM has none — it was not omitted "
                     "or invented.")
    elif result.get("degraded"):
        lines.append("The facility lookup service is unreachable, so no handover points can be listed.")
    else:
        lines.append("No handover points mapped within the search radius.")

    nearest = result.get("nearest_network_points") or []
    if nearest:
        lines.append("\nNearest routable corridor nodes (use one of these as an origin or destination):")
        for n in nearest:
            lines.append(f"- {n['label']} · {n.get('distance_km')} km · id {n['location_id']}")
    return "\n".join(lines)


def tool_corridor_status(args):
    state = args.get("state")
    only_problems = args.get("only_problems", False)
    result = _call_api("/api/ner/segments")
    segments = result.get("segments") or []
    if state:
        segments = [s for s in segments if (s.get("source_state") or "").lower() == state.lower()]
    if only_problems:
        segments = [s for s in segments if s.get("impassable") or s.get("road_status") != "Open"]
    if not segments:
        return "No corridors match that filter."
    segments.sort(key=lambda s: s.get("accessibility_score", 100))
    lines = [f"{len(segments)} corridor(s)" + (f" in {state}" if state else "") + ":"]
    for s in segments[: args.get("limit", 15)]:
        flag = " [CLOSED — excluded from routing]" if s.get("impassable") else ""
        lines.append(
            f"- {s['source_name']} -> {s['destination_name']} ({s.get('highway_corridor')}): "
            f"accessibility {round(s.get('accessibility_score', 0))}/100, "
            f"{s.get('road_status')}{flag}"
        )
    return "\n".join(lines) + DISCLAIMER


def tool_network_overview(args):
    data = _call_api("/api/ner/dashboard")
    lines = [
        f"Network accessibility: {data.get('overall_accessibility')}/100 across "
        f"{data.get('total_segments')} corridors.",
        f"Average predicted disruption risk: {data.get('average_disruption_probability_percent')}%.",
        f"Impassable corridors: {data.get('impassable_count')}.",
        f"Active incidents (7 days): {data.get('active_incident_count')}.",
    ]
    high_risk = data.get("high_risk_corridors") or []
    if high_risk:
        lines.append("\nLowest-scoring corridors:")
        for c in high_risk[:5]:
            lines.append(
                f"- {c['source_name']} -> {c['destination_name']}: "
                f"{round(c.get('accessibility_score', 0))}/100 ({c.get('road_status')})"
            )
    return "\n".join(lines) + DISCLAIMER


def tool_report_incident(args):
    import uuid

    payload = {
        "client_uuid": args.get("client_uuid") or f"mcp-{uuid.uuid4()}",
        "type": args["type"],
        "severity": args.get("severity", 3),
        "description": args.get("description", ""),
        "latitude": args["latitude"],
        "longitude": args["longitude"],
        "reporter_name": args.get("reporter_name"),
    }
    result = _call_api("/api/ner/incidents", "POST", payload)
    incident = result.get("incident") or {}
    match = result.get("attribution") or {}

    # Where it landed, in words. "Against corridor RS002" alone hides the failure that
    # matters: a coordinate the network has nothing near gets matched to whatever happens to
    # be least far away, and the caller has no way to notice unless the distance is stated.
    if match.get("on_network"):
        distance = match.get("distance_km")
        where = (
            f"matched to the {match.get('segment_label')} corridor "
            f"({distance} km from it)"
        )
    else:
        where = (
            f"not matched to any corridor — the nearest is {match.get('distance_km')} km away, "
            f"beyond the {match.get('snap_radius_km')} km limit, so it will not affect routing. "
            "If that is unexpected, the coordinates are worth re-checking"
        )

    return (
        f"Report filed as #{incident.get('id')}, {where}.\n"
        f"Status: {incident.get('verification_status')}.\n\n"
        "An unverified report raises a corridor's risk but never closes it. Closing a road "
        "requires two different District Verifiers to agree, and that decision is made by "
        "people in the review queue — not by this tool and not by any model."
    )


def tool_cargo_profiles(args):
    result = _call_api("/api/ner/cargo-types")
    lines = ["Cargo types and how each reweights the five routing objectives:"]
    for cargo in result.get("cargo_types") or []:
        name = cargo.get("id") or cargo.get("name")
        lines.append(f"- {name}: {cargo.get('rationale') or cargo.get('description', '')}")
    lines.append("\nUrgency (low | normal | high | critical) scales the time weighting on top.")
    return "\n".join(lines)


TOOLS = [
    {
        "name": "plan_route",
        "description": (
            "Plan a freight consignment across India's North Eastern Region using risk-aware "
            "multi-objective routing. Balances time, cost, corridor accessibility, disruption "
            "risk and reliability, reweighted by cargo type and urgency. Verified severe "
            "blockages are removed from the graph entirely, so a returned route is one that "
            "is currently passable. Returns the recommended route plus alternatives, each "
            "with an explanation. Use search_places first if you have place names rather "
            "than location ids."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "Location id, e.g. LOC002 (from search_places)"},
                "destination": {"type": "string", "description": "Location id, e.g. LOC007"},
                "cargo_type": {
                    "type": "string",
                    "enum": ["general", "relief", "medicine", "perishable", "fuel", "construction"],
                    "description": "Reweights the objectives; call cargo_profiles to see how.",
                },
                "urgency": {"type": "string", "enum": ["low", "normal", "high", "critical"]},
                "weight_kg": {"type": "number", "description": "Consignment weight; sizes the fleet and steps the cost."},
            },
            "required": ["origin", "destination"],
        },
    },
    {
        "name": "search_places",
        "description": (
            "Find a place by name across the eight North Eastern states and the Siliguri "
            "corridor. Returns corridor network nodes (usable directly as a route origin or "
            "destination, with a location id) and real nearby places from OpenStreetMap "
            "(which must be snapped to a node first). Use this to turn a town, market or "
            "station name into something plan_route accepts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Place name or partial name, e.g. 'silchar'"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "nearby_handover_points",
        "description": (
            "List places near a coordinate where cargo can physically change hands — post "
            "offices, courier counters, depots, bus and railway stations, warehouses, fuel "
            "stops — with phone numbers and opening hours where OpenStreetMap records them. "
            "Also returns the nearest routable corridor nodes. Use after plan_route to tell "
            "a shipper where to actually take the goods."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
                "radius_km": {"type": "number", "minimum": 1, "maximum": 25},
            },
            "required": ["latitude", "longitude"],
        },
    },
    {
        "name": "corridor_status",
        "description": (
            "Current accessibility of road corridors, worst first. Filter by state, or to "
            "only degraded and closed corridors. Use to answer 'which roads are in trouble' "
            "without planning a specific consignment."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "e.g. Assam, Manipur, Meghalaya"},
                "only_problems": {"type": "boolean", "description": "Only degraded or closed corridors"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        },
    },
    {
        "name": "network_overview",
        "description": (
            "Region-wide summary: overall accessibility, average predicted disruption risk, "
            "how many corridors are impassable, active incident count, and the worst-scoring "
            "corridors. Use for a situational briefing."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "report_incident",
        "description": (
            "File a field report of an obstruction — landslide, flood, road block, bridge "
            "damage, accident. The report is matched to the nearest corridor and raises its "
            "risk immediately, but never closes a road on its own: closure requires two "
            "different human verifiers. Use when a user reports a blockage they have observed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["landslide", "flood", "road_block", "bridge_damage", "accident", "other"],
                },
                "severity": {"type": "integer", "minimum": 1, "maximum": 5,
                             "description": "1 minor to 5 impassable"},
                "description": {"type": "string"},
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
                "reporter_name": {"type": "string"},
            },
            "required": ["type", "latitude", "longitude"],
        },
    },
    {
        "name": "cargo_profiles",
        "description": (
            "The available cargo types and how each reweights the routing objectives — why "
            "relief supplies and perishables can take different corridors between the same "
            "two towns. Use to choose a cargo_type for plan_route, or to explain a result."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]

HANDLERS = {
    "plan_route": tool_plan_route,
    "search_places": tool_search_places,
    "nearby_handover_points": tool_nearby_handover_points,
    "corridor_status": tool_corridor_status,
    "network_overview": tool_network_overview,
    "report_incident": tool_report_incident,
    "cargo_profiles": tool_cargo_profiles,
}


# ---------------------------------------------------------------- JSON-RPC loop

def _respond(message_id, result=None, error=None):
    payload = {"jsonrpc": "2.0", "id": message_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def handle(message):
    method = message.get("method")
    message_id = message.get("id")
    params = message.get("params") or {}

    # Notifications carry no id and must never be answered.
    if message_id is None:
        return

    if method == "initialize":
        # Echo the client's protocol version when it names one: this server's surface is
        # plain tools, which every revision supports, so agreeing with the client is safer
        # than asserting a version it may not know.
        version = params.get("protocolVersion") or PROTOCOL_FALLBACK
        _respond(message_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    elif method == "tools/list":
        _respond(message_id, {"tools": TOOLS})
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if handler is None:
            _respond(message_id, error={"code": -32601, "message": f"Unknown tool: {name}"})
            return
        try:
            text = handler(args)
            _respond(message_id, {"content": [{"type": "text", "text": text}], "isError": False})
        except KeyError as e:
            _respond(message_id, {
                "content": [{"type": "text", "text": f"Missing required argument: {e}"}],
                "isError": True,
            })
        except Exception as e:
            # Reported as tool output rather than a protocol error, so the model can read the
            # reason and retry or explain, instead of the call simply vanishing.
            _respond(message_id, {
                "content": [{"type": "text", "text": f"Error: {e}"}],
                "isError": True,
            })
    elif method == "ping":
        _respond(message_id, {})
    else:
        _respond(message_id, error={"code": -32601, "message": f"Unknown method: {method}"})


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            handle(message)
        except Exception as e:  # a malformed request must not kill the server
            print(f"internal error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
