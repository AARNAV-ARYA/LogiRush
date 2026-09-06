# src/api/shipment_routes.py
"""
Shipment lifecycle API.

Creating a shipment plans a route and stores a SNAPSHOT of that route on the record. The
snapshot matters: conditions change constantly (new incidents, new predictions), so without
it there would be no way to answer "what were we told when we dispatched this?" — which is
exactly the question asked after something goes wrong.

`POST /shipments/<id>/replan` re-plans against current conditions and returns a diff against
the stored snapshot. That is the concrete demonstration of "dynamically adapt route
recommendations": dispatch a shipment, report a landslide, replan, and the response states
plainly that the route changed and why.
"""

import json
import logging
import uuid

from flask import Blueprint, jsonify, request

from src.modeling.cargo_profiles import CARGO_PROFILES, DEFAULT_URGENCY, URGENCY_TIME_MULTIPLIER
from src.modeling.transport_modes import DEFAULT_WEIGHT_KG
from src.services.routing_service import routing_service

logger = logging.getLogger("shipment_routes")

shipment_bp = Blueprint("shipments", __name__, url_prefix="/api/ner/shipments")

SHIPMENT_STATUSES = ["planned", "dispatched", "in_transit", "delivered", "cancelled"]


def _error(message, status=400):
    return jsonify({"status": "error", "message": message}), status


def _validate(payload: dict):
    origin = payload.get("origin_id") or payload.get("origin")
    destination = payload.get("destination_id") or payload.get("destination")
    if not origin or not destination:
        return None, "'origin_id' and 'destination_id' are required"
    if origin == destination:
        return None, "'origin_id' and 'destination_id' must be different"

    cargo_type = str(payload.get("cargo_type", "general")).strip().lower()
    if cargo_type not in CARGO_PROFILES:
        return None, f"'cargo_type' must be one of {sorted(CARGO_PROFILES)}"

    urgency = str(payload.get("urgency", DEFAULT_URGENCY)).strip().lower()
    if urgency not in URGENCY_TIME_MULTIPLIER:
        return None, f"'urgency' must be one of {sorted(URGENCY_TIME_MULTIPLIER)}"

    weight_kg = payload.get("weight_kg")
    if weight_kg is not None:
        try:
            weight_kg = float(weight_kg)
        except (TypeError, ValueError):
            return None, "'weight_kg' must be a number"
        if weight_kg < 0:
            return None, "'weight_kg' cannot be negative"

    priority = payload.get("priority")
    if priority is not None:
        try:
            priority = int(priority)
        except (TypeError, ValueError):
            return None, "'priority' must be an integer"
        if not 1 <= priority <= 5:
            return None, "'priority' must be between 1 and 5"

    return {
        "client_uuid": str(payload.get("client_uuid") or uuid.uuid4()),
        "origin_id": origin,
        "destination_id": destination,
        "cargo_type": cargo_type,
        "urgency": urgency,
        "weight_kg": weight_kg,
        "priority": priority,
    }, None


def _summarise_route(route: dict) -> dict:
    """Compact form of a route, for storage and for diffing on replan."""
    if not route:
        return {}
    return {
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
        # Carried so a replan can tell the operator not just that the road changed, but that
        # the vehicle class or fleet size the consignment was costed on has changed too.
        "weight_kg": route.get("weight_kg"),
        "priced_mode": route.get("priced_mode"),
        "priced_mode_label": route.get("priced_mode_label"),
        "vehicles_required": route.get("vehicles_required"),
    }


@shipment_bp.route("", methods=["POST"])
def create_shipment():
    try:
        payload = request.get_json(silent=True) or {}
        cleaned, error = _validate(payload)
        if error:
            return _error(error)

        try:
            plan = routing_service.plan(
                cleaned["origin_id"],
                cleaned["destination_id"],
                cargo_type=cleaned["cargo_type"],
                urgency=cleaned["urgency"],
                weight_kg=cleaned.get("weight_kg") or DEFAULT_WEIGHT_KG,
            )
        except LookupError as e:
            return _error(str(e), 404)
        except ValueError as e:
            return _error(str(e))

        from src.db.models import Shipment
        from src.db.session import get_session

        session = get_session()
        try:
            existing = (
                session.query(Shipment)
                .filter(Shipment.client_uuid == cleaned["client_uuid"])
                .one_or_none()
            )
            if existing:
                # Idempotent, same contract as incident sync: replaying a queued shipment
                # from an offline client must not create a second one.
                return jsonify({
                    "status": "success",
                    "created": False,
                    "duplicate": True,
                    "shipment": existing.to_dict(),
                    "planned_route": json.loads(existing.planned_route_json or "null"),
                }), 200

            shipment = Shipment(
                **cleaned,
                status="planned",
                planned_route_json=json.dumps(_summarise_route(plan["recommended_route"])),
            )
            session.add(shipment)
            session.commit()
            record = shipment.to_dict()
        finally:
            session.close()

        return jsonify({
            "status": "success",
            "created": True,
            "duplicate": False,
            "shipment": record,
            "planned_route": plan["recommended_route"],
            "alternative_routes": plan["alternative_routes"],
            "objective_weights": plan["objective_weights"],
            "routable": plan["recommended_route"] is not None,
            "message": plan.get("message"),
        }), 201
    except Exception as e:
        logger.error(f"Error creating shipment: {e}")
        return _error(str(e), 500)


@shipment_bp.route("", methods=["GET"])
def list_shipments():
    try:
        from src.db.models import Shipment
        from src.db.session import get_session

        limit = min(int(request.args.get("limit", 100)), 500)
        status_filter = request.args.get("status")

        session = get_session()
        try:
            query = session.query(Shipment)
            if status_filter:
                if status_filter not in SHIPMENT_STATUSES:
                    return _error(f"'status' must be one of {SHIPMENT_STATUSES}")
                query = query.filter(Shipment.status == status_filter)
            rows = query.order_by(Shipment.created_at.desc()).limit(limit).all()
            shipments = []
            for row in rows:
                item = row.to_dict()
                item["planned_route"] = json.loads(row.planned_route_json or "null")
                shipments.append(item)
        finally:
            session.close()

        return jsonify({"status": "success", "count": len(shipments), "shipments": shipments}), 200
    except Exception as e:
        logger.error(f"Error listing shipments: {e}")
        return _error(str(e), 500)


@shipment_bp.route("/<int:shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    try:
        from src.db.models import Shipment
        from src.db.session import get_session

        session = get_session()
        try:
            shipment = session.get(Shipment, shipment_id)
            if shipment is None:
                return _error(f"Shipment {shipment_id} not found", 404)
            item = shipment.to_dict()
            item["planned_route"] = json.loads(shipment.planned_route_json or "null")
        finally:
            session.close()

        return jsonify({"status": "success", "shipment": item}), 200
    except Exception as e:
        logger.error(f"Error fetching shipment {shipment_id}: {e}")
        return _error(str(e), 500)


@shipment_bp.route("/<int:shipment_id>/status", methods=["POST"])
def update_status(shipment_id):
    try:
        from src.db.models import Shipment
        from src.db.session import get_session

        payload = request.get_json(silent=True) or {}
        new_status = str(payload.get("status", "")).strip().lower()
        if new_status not in SHIPMENT_STATUSES:
            return _error(f"'status' must be one of {SHIPMENT_STATUSES}")

        session = get_session()
        try:
            shipment = session.get(Shipment, shipment_id)
            if shipment is None:
                return _error(f"Shipment {shipment_id} not found", 404)
            shipment.status = new_status
            session.commit()
            record = shipment.to_dict()
        finally:
            session.close()

        return jsonify({"status": "success", "shipment": record}), 200
    except Exception as e:
        logger.error(f"Error updating shipment {shipment_id}: {e}")
        return _error(str(e), 500)


@shipment_bp.route("/<int:shipment_id>/replan", methods=["POST"])
def replan_shipment(shipment_id):
    """Re-plan against current conditions and diff against the stored snapshot."""
    try:
        from src.db.models import Shipment
        from src.db.session import get_session

        session = get_session()
        try:
            shipment = session.get(Shipment, shipment_id)
            if shipment is None:
                return _error(f"Shipment {shipment_id} not found", 404)
            original = json.loads(shipment.planned_route_json or "null")
            origin_id = shipment.origin_id
            destination_id = shipment.destination_id
            cargo_type = shipment.cargo_type
            urgency = shipment.urgency
            weight_kg = shipment.weight_kg
        finally:
            session.close()

        update_snapshot = bool((request.get_json(silent=True) or {}).get("update_snapshot", False))

        try:
            plan = routing_service.plan(
                origin_id,
                destination_id,
                cargo_type=cargo_type,
                urgency=urgency,
                weight_kg=(original or {}).get("weight_kg") or weight_kg or DEFAULT_WEIGHT_KG,
            )
        except (LookupError, ValueError) as e:
            return _error(str(e), 404)

        new_route = plan["recommended_route"]
        new_summary = _summarise_route(new_route)

        changed = bool(original) and bool(new_summary) and original.get("path") != new_summary.get("path")
        now_unroutable = new_route is None

        differences = {}
        if original and new_summary:
            for field in ("eta_hours", "total_distance_km", "worst_segment_accessibility",
                          "peak_segment_risk_percent"):
                before, after = original.get(field), new_summary.get(field)
                if before is not None and after is not None and before != after:
                    differences[field] = {
                        "before": before,
                        "after": after,
                        "delta": round(after - before, 2),
                    }

        if update_snapshot and new_summary:
            session = get_session()
            try:
                shipment = session.get(Shipment, shipment_id)
                shipment.planned_route_json = json.dumps(new_summary)
                session.commit()
            finally:
                session.close()

        if now_unroutable:
            summary = ("No route is currently available for this shipment — every corridor "
                       "between these locations is impassable.")
        elif changed:
            summary = ("Conditions changed: a different route is now recommended for this "
                       "shipment.")
        else:
            summary = "Conditions checked: the original route is still the best available."

        return jsonify({
            "status": "success",
            "shipment_id": shipment_id,
            "route_changed": changed,
            "routable": not now_unroutable,
            "summary": summary,
            "original_route": original,
            "current_route": new_route,
            "differences": differences,
            "snapshot_updated": bool(update_snapshot and new_summary),
            "computation_seconds": plan["computation_seconds"],
        }), 200
    except Exception as e:
        logger.error(f"Error replanning shipment {shipment_id}: {e}")
        return _error(str(e), 500)
