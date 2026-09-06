"""Authentication and authorisation for the NER platform.

Who may do what, and why it is drawn this way.

The question this module answers is "who verifies a report?", and the honest answer in the
North Eastern context is: not whoever is looking at the screen. A verified severity-5
landslide removes a corridor from the routing graph, so verification is an operational
decision with a cost in both directions — a wrong closure strands a district for days, a
missed one sends a convoy into a live slip. Three constraints follow, and each is enforced
here rather than in the interface, because a rule that lives only in a React component is
not a rule:

  1. Jurisdiction. A verifier acts only in the states they are assigned to. Someone in the
     Shillong control room has no business closing a highway in Arunachal Pradesh, and an
     incident whose state cannot be resolved escalates to a controller rather than falling
     to whoever reaches it first.

  2. No self-verification. The reporter of a report can never be the one who confirms it,
     whatever their role. This is the cheapest possible guard against a single person
     manufacturing a closure, and it costs nothing when the roster is healthy.

  3. Two-person rule for closures. A verification that would actually shut a road needs a
     second, different verifier to countersign. Until then the report sits in
     `awaiting_countersign` and the corridor stays open. Every other verification takes
     effect immediately — the rule is scoped to the irreversible-in-practice case, because
     applying it everywhere would just teach people to route around it.

Roles:
  reporter    submits reports. The public, volunteers, drivers, panchayat staff.
  verifier    confirms or rejects reports inside an assigned jurisdiction. DDMA officers,
              PWD engineers, district control room staff.
  controller  state-level oversight (ASDMA and equivalents). Acts anywhere, is the only role
              that can delete, and is the escalation path for unplaceable reports.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

logger = logging.getLogger(__name__)

TOKEN_TTL_HOURS = 12


def _utcnow():
    return datetime.now(timezone.utc)


def hash_password(raw: str) -> str:
    return generate_password_hash(raw)


def issue_token(session, user) -> dict:
    from src.db.models import AuthToken

    token = secrets.token_urlsafe(32)
    expires = _utcnow() + timedelta(hours=TOKEN_TTL_HOURS)
    session.add(AuthToken(token=token, user_id=user.id, expires_at=expires))
    session.commit()
    return {"token": token, "expires_at": expires.isoformat()}


def authenticate(session, username: str, password: str):
    """Return the user for these credentials, or None.

    The same None is returned for an unknown username, a wrong password and a deactivated
    account, so the endpoint cannot be used to enumerate the roster.
    """
    from src.db.models import User

    user = session.query(User).filter(User.username == username).first()
    if user is None or not user.active:
        return None
    if not check_password_hash(user.password_hash, password or ""):
        return None
    return user


def resolve_token(session, token: str):
    from src.db.models import AuthToken

    if not token:
        return None
    row = session.query(AuthToken).filter(AuthToken.token == token).first()
    if row is None:
        return None
    expires = row.expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires is not None and expires < _utcnow():
        session.delete(row)
        session.commit()
        return None
    user = row.user
    return user if (user and user.active) else None


def _bearer():
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def current_user(session):
    return resolve_token(session, _bearer())


def require_role(*allowed):
    """Guard an endpoint by role.

    Opens its own session and attaches the user to `g` so the view can read it without
    repeating the lookup.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            from src.db.session import get_session

            session = get_session()
            try:
                user = current_user(session)
                if user is None:
                    # Same envelope as the rest of the API ({"status","message"}), because
                    # the client parses one key and a second shape just surfaces as a blank
                    # error toast.
                    return jsonify({
                        "status": "error",
                        "message": "Sign in to perform this action.",
                    }), 401
                if allowed and user.role not in allowed:
                    return jsonify({
                        "status": "error",
                        "message": (
                            f"This action needs one of: {', '.join(allowed)}. "
                            f"Your role is '{user.role}'."
                        ),
                    }), 403
                # Detach a plain snapshot: the request-scoped session closes here, and the
                # view must not touch a stale ORM instance afterwards.
                g.user_id = user.id
                g.user = user.to_dict()
            finally:
                session.close()
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def optional_user():
    """Attach the caller to `g` if they presented a valid token, without demanding one.

    Reporting stays open to anonymous submissions — a stranded driver with no account is
    exactly who this platform needs to hear from — but when a report does arrive with a
    token we record who sent it, which is what makes the no-self-verification rule possible.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            from src.db.session import get_session

            g.user_id = None
            g.user = None
            try:
                session = get_session()
                try:
                    user = current_user(session)
                    if user is not None:
                        g.user_id = user.id
                        g.user = user.to_dict()
                finally:
                    session.close()
            except Exception as e:  # auth must never take reporting offline
                logger.warning(f"optional_user failed open: {e}")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ------------------------------------------------------------------ permission rules

def needs_countersign(incident) -> bool:
    """Would verifying this report actually close a corridor?"""
    from src.db.models import COUNTERSIGN_SEVERITY, COUNTERSIGN_TYPES

    return (
        incident.severity >= COUNTERSIGN_SEVERITY
        and incident.incident_type in COUNTERSIGN_TYPES
        and bool(incident.segment_id)
    )


def can_act_on(user: dict, incident, incident_state: str | None, action: str):
    """May this user take this action on this incident? Returns (bool, reason).

    One function, called by every mutating endpoint, so the rules cannot drift apart between
    verify and resolve and delete.
    """
    role = user.get("role")

    if action == "delete":
        if role != "controller":
            return False, (
                "Only a State Controller can delete a report. Verifiers can reject a false "
                "report or resolve one that is over — both keep the record."
            )
        return True, None

    if action == "withdraw":
        if incident.reported_by_id and incident.reported_by_id == user.get("id"):
            if incident.verification_status != "unverified":
                return False, "This report has already been acted on and can no longer be withdrawn."
            return True, None
        return False, "Only the person who filed a report can withdraw it."

    if role == "reporter":
        return False, "Field Reporters submit reports; verification is done by a District Verifier."

    if role not in ("verifier", "controller"):
        return False, "Your role cannot act on reports."

    # No self-verification, at any rank. A controller who filed a report is still the
    # reporter of it, and the second pair of eyes is the entire point.
    if incident.reported_by_id and incident.reported_by_id == user.get("id"):
        return False, (
            "You filed this report, so you cannot be the one to confirm it. "
            "Pass it to another verifier."
        )

    if role == "verifier":
        states = user.get("jurisdiction") or []
        if not incident_state:
            return False, (
                "This report could not be placed in a state, so it is escalated to a "
                "State Controller."
            )
        if incident_state not in states:
            return False, (
                f"{incident_state} is outside your jurisdiction "
                f"({', '.join(states) or 'none assigned'})."
            )

    return True, None
