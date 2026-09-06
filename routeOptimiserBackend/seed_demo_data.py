#!/usr/bin/env python
"""
Seed demonstration data (incidents + shipments) into the database.

Run before a demo so the dashboard, map and shipment list have something to show:

    python seed_demo_data.py            # add demo data if not already present
    python seed_demo_data.py --reset    # delete existing demo rows first

Every row is tagged with a DEMO_ prefix on client_uuid so --reset can remove exactly what
this script created and nothing a real user entered. The incidents chosen tell a coherent
story: a verified severe landslide that closes one corridor, a couple of unverified reports
that raise risk without closing anything, and one rejected report that must be ignored.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

from src.db.models import Incident, Shipment
from src.db.session import get_session, init_db

DEMO_PREFIX = "DEMO_"


def _hours_ago(hours):
    return datetime.now(timezone.utc) - timedelta(hours=hours)


DEMO_INCIDENTS = [
    {
        "client_uuid": f"{DEMO_PREFIX}landslide_nh29",
        "incident_type": "landslide",
        "severity": 5,
        "description": "Major slip across both lanes near Kohima. Road fully blocked.",
        "latitude": 25.79,
        "longitude": 93.92,
        "segment_id": "RS022",
        "verification_status": "verified",
        "reporter_name": "District Disaster Cell",
        "reported_at": _hours_ago(6),
    },
    {
        "client_uuid": f"{DEMO_PREFIX}flood_brahmaputra",
        "incident_type": "flood",
        "severity": 3,
        "description": "Water over the carriageway near Nagaon, passable with care.",
        "latitude": 26.34,
        "longitude": 92.68,
        "segment_id": "RS005",
        "verification_status": "verified",
        "reporter_name": "Highway Patrol",
        "reported_at": _hours_ago(20),
    },
    {
        "client_uuid": f"{DEMO_PREFIX}rockfall_nh306",
        "incident_type": "road_block",
        "severity": 3,
        "description": "Boulders on the Silchar-Aizawl stretch, single lane open.",
        "latitude": 24.30,
        "longitude": 92.74,
        "segment_id": "RS016",
        "verification_status": "unverified",
        "reporter_name": "Local transporter",
        "reported_at": _hours_ago(30),
    },
    {
        "client_uuid": f"{DEMO_PREFIX}bridge_check_nh10",
        "incident_type": "bridge_damage",
        "severity": 4,
        "description": "Cracking reported on an approach span; awaiting engineer inspection.",
        "latitude": 27.10,
        "longitude": 88.50,
        "segment_id": "RS001",
        "verification_status": "unverified",
        "reporter_name": "Bus operator",
        "reported_at": _hours_ago(48),
    },
    {
        "client_uuid": f"{DEMO_PREFIX}false_report",
        "incident_type": "landslide",
        "severity": 5,
        "description": "Unconfirmed rumour; inspected and found clear.",
        "latitude": 25.51,
        "longitude": 90.21,
        "segment_id": "RS014",
        "verification_status": "rejected",
        "reporter_name": "Anonymous",
        "reported_at": _hours_ago(72),
    },
]

DEMO_SHIPMENTS = [
    {
        "client_uuid": f"{DEMO_PREFIX}ship_medicine",
        "origin_id": "LOC002",
        "destination_id": "LOC016",
        "cargo_type": "medicine",
        "urgency": "critical",
        "weight_kg": 850,
        "priority": 1,
        "status": "dispatched",
    },
    {
        "client_uuid": f"{DEMO_PREFIX}ship_relief",
        "origin_id": "LOC001",
        "destination_id": "LOC012",
        "cargo_type": "relief",
        "urgency": "high",
        "weight_kg": 4200,
        "priority": 1,
        "status": "planned",
    },
    {
        "client_uuid": f"{DEMO_PREFIX}ship_perishable",
        "origin_id": "LOC002",
        "destination_id": "LOC007",
        "cargo_type": "perishable",
        "urgency": "high",
        "weight_kg": 1800,
        "priority": 3,
        "status": "in_transit",
    },
    {
        "client_uuid": f"{DEMO_PREFIX}ship_general",
        "origin_id": "LOC024",
        "destination_id": "LOC002",
        "cargo_type": "general",
        "urgency": "normal",
        "weight_kg": 12000,
        "priority": 4,
        "status": "delivered",
    },
]


def reset(session):
    incidents = session.query(Incident).filter(Incident.client_uuid.like(f"{DEMO_PREFIX}%")).all()
    shipments = session.query(Shipment).filter(Shipment.client_uuid.like(f"{DEMO_PREFIX}%")).all()
    for row in incidents + shipments:
        session.delete(row)
    session.commit()
    return len(incidents), len(shipments)


def seed(session):
    from src.services.routing_service import routing_service

    created_incidents = 0
    for data in DEMO_INCIDENTS:
        exists = (
            session.query(Incident).filter(Incident.client_uuid == data["client_uuid"]).one_or_none()
        )
        if exists:
            continue
        session.add(Incident(**data))
        created_incidents += 1
    session.commit()

    # Incidents change conditions, so plan shipment routes only after they are committed.
    routing_service.invalidate()

    created_shipments = 0
    for data in DEMO_SHIPMENTS:
        exists = (
            session.query(Shipment).filter(Shipment.client_uuid == data["client_uuid"]).one_or_none()
        )
        if exists:
            continue

        planned_route_json = None
        try:
            plan = routing_service.plan(
                data["origin_id"], data["destination_id"],
                cargo_type=data["cargo_type"], urgency=data["urgency"],
            )
            route = plan["recommended_route"]
            if route:
                planned_route_json = json.dumps({
                    "path": route["path"],
                    "path_names": route["path_names"],
                    "eta_hours": route["eta_hours"],
                    "total_distance_km": route["total_distance_km"],
                    "estimated_cost_inr": route["estimated_cost_inr"],
                    "accessibility_score": route["accessibility_score"],
                    "worst_segment_accessibility": route["worst_segment_accessibility"],
                    "risk_score": route["risk_score"],
                    "peak_segment_risk_percent": route["peak_segment_risk_percent"],
                    "segments": [s["segment_id"] for s in route["segments"]],
                })
        except Exception as e:
            print(f"  ! could not plan route for {data['client_uuid']}: {e}")

        session.add(Shipment(**data, planned_route_json=planned_route_json))
        created_shipments += 1
    session.commit()
    return created_incidents, created_shipments


def main():
    parser = argparse.ArgumentParser(description="Seed demo data for the NER platform.")
    parser.add_argument("--reset", action="store_true", help="Delete existing demo rows first")
    args = parser.parse_args()

    init_db()
    session = get_session()
    try:
        if args.reset:
            removed = reset(session)
            print(f"Removed {removed[0]} demo incident(s) and {removed[1]} demo shipment(s).")
        incidents, shipments = seed(session)
        print(f"Seeded {incidents} incident(s) and {shipments} shipment(s).")
        print("Note: this is clearly-labelled demonstration data, not real reports.")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
