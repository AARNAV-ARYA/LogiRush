"""Session endpoints: sign in, sign out, who am I.

Kept separate from ner_routes so the authorisation surface is one small file somebody can
read end to end before trusting it.
"""

import logging

from flask import Blueprint, g, jsonify, request

from src.api.auth import authenticate, issue_token, require_role
from src.db.session import get_session

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _error(message, code=400):
    return jsonify({"status": "error", "message": message}), code


@auth_bp.route("/login", methods=["POST"])
def login():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip().lower()
    password = str(payload.get("password", ""))

    if not username or not password:
        return _error("Username and password are required.")

    session = get_session()
    try:
        user = authenticate(session, username, password)
        if user is None:
            # An empty roster is a setup problem, not a wrong password, and telling someone
            # their credentials are wrong when no account exists sends them hunting for a
            # typo that isn't there. Saying "there are no accounts" leaks nothing: it is a
            # statement about the installation, not about any particular username.
            from src.db.models import User

            if session.query(User).count() == 0:
                return _error(
                    "No operator accounts exist in this database yet. Run "
                    "`python seed_users.py` in routeOptimiserBackend, or restart the server "
                    "to have the demonstration roster created automatically.",
                    503,
                )
            # Otherwise one message for every failure mode, so this cannot enumerate the roster.
            return _error("Those credentials were not recognised.", 401)
        token = issue_token(session, user)
        return jsonify({"status": "success", "user": user.to_dict(), **token}), 200
    except Exception as e:
        logger.error(f"Login failed: {e}")
        return _error("Sign-in is unavailable right now.", 500)
    finally:
        session.close()


@auth_bp.route("/logout", methods=["POST"])
def logout():
    from src.db.models import AuthToken

    header = request.headers.get("Authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    if not token:
        return jsonify({"status": "success"}), 200

    session = get_session()
    try:
        row = session.query(AuthToken).filter(AuthToken.token == token).first()
        if row is not None:
            session.delete(row)
            session.commit()
        return jsonify({"status": "success"}), 200
    finally:
        session.close()


@auth_bp.route("/me", methods=["GET"])
@require_role()
def me():
    return jsonify({"status": "success", "user": g.user}), 200


@auth_bp.route("/roles", methods=["GET"])
def roles():
    """What each role may do, served from the same place the UI reads it.

    Public on purpose: the access model is a design decision this project wants to be able to
    explain, not a secret. Knowing that a verifier is jurisdiction-scoped does not help you
    get past it.
    """
    return jsonify({
        "status": "success",
        "roles": [
            {
                "id": "reporter",
                "label": "Field Reporter",
                "who": "Volunteers, drivers, panchayat staff, the public",
                "can": ["Submit incident reports (online or offline)",
                        "Withdraw their own report before anyone acts on it",
                        "View the corridor network"],
                "cannot": ["Verify or reject any report", "Delete anything"],
            },
            {
                "id": "verifier",
                "label": "District Verifier",
                "who": "DDMA officers, PWD engineers, district control room staff",
                "can": ["Verify or reject reports inside their assigned states",
                        "Mark a report resolved once the obstruction is cleared",
                        "Countersign another verifier's road closure"],
                "cannot": ["Act outside their jurisdiction",
                           "Verify a report they filed themselves",
                           "Single-handedly close a road (needs a countersign)",
                           "Delete a report"],
            },
            {
                "id": "controller",
                "label": "State Controller",
                "who": "ASDMA / state emergency operations centre",
                "can": ["Everything a verifier can, in every state",
                        "Handle reports that could not be placed in a state",
                        "Delete a spam or duplicate report, with a logged reason"],
                "cannot": ["Verify a report they filed themselves"],
            },
        ],
        "rules": [
            "Verification is always a human decision. The prediction model never sets a status.",
            "Nobody can verify a report they filed, whatever their role.",
            "Closing a road (severity 5, blocking type) needs two different verifiers.",
            "An unverified report raises a corridor's risk but never closes it.",
            "Deleting is for spam and duplicates. A real event that is over is 'resolved', "
            "which reopens the road and keeps the record.",
        ],
    }), 200
