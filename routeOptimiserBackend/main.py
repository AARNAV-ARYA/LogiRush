from flask import Flask, jsonify
from flask_cors import CORS
from src.api.auth_routes import auth_bp
from src.api.ner_routes import ner_bp
from src.api.shipment_routes import shipment_bp
from src.db.session import init_db
import logging
import os
import sys
import threading
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# An incident report carries its photograph inline as a base64 data URI, and a phone flushing
# an offline queue can send several at once — so the request bodies here are legitimately
# large, and there has to be a ceiling. Without one, a malformed or hostile client can make
# the server buffer an unbounded body; with one, Flask rejects it before reading it. 16 MB is
# roughly a dozen downscaled field photographs, which is more than any real queue flush.
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_CONTENT_MB", "16")) * 1024 * 1024
# CORS_ORIGINS is a comma-separated allowlist in production (e.g. the Vercel frontend URL).
# Defaults to "*" so local development and the existing frontend keep working unchanged.
_cors_origins = os.environ.get("CORS_ORIGINS", "*")
CORS(app, resources={r"/api/*": {"origins": _cors_origins.split(",") if _cors_origins != "*" else "*"}})
app.register_blueprint(auth_bp)
app.register_blueprint(ner_bp)
app.register_blueprint(shipment_bp)

# Create incident/shipment tables if absent. Non-fatal: the cross-border optimiser and the
# read-only accessibility endpoints must keep working even if the database is unreachable.
try:
    init_db()

    # Bootstrap the operator roster on first run. Without accounts nobody can reach the
    # review queue, and "no accounts exist" is indistinguishable from "the login is broken"
    # to anyone who has just cloned this. Only fires when the table is empty; set
    # NER_DISABLE_DEMO_SEED=1 to skip it in a deployment with a real roster.
    if os.environ.get("NER_DISABLE_DEMO_SEED", "").strip() not in ("1", "true", "yes"):
        from src.db.roster import ensure_roster
        from src.db.session import get_session

        _session = get_session()
        try:
            _created = ensure_roster(_session)
            if _created:
                logging.getLogger(__name__).warning(
                    "Seeded %d demonstration account(s): %s. These are PUBLISHED demo "
                    "credentials (see seed_users.py) — set NER_DISABLE_DEMO_SEED=1 and use a "
                    "real roster before deploying.",
                    len(_created), ", ".join(_created),
                )
        finally:
            _session.close()
except Exception as _db_error:  # pragma: no cover - depends on deployment environment
    logging.getLogger(__name__).warning(f"Database init skipped: {_db_error}")


@app.errorhandler(413)
def payload_too_large(_error):
    """Answer an oversized upload in the shape every client here already parses.

    Flask's default 413 is an HTML page, and both clients read `message` out of JSON — so the
    reporter would otherwise be told "Request failed (413)" and have no idea that the
    photograph was the problem.
    """
    limit_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
    return jsonify({
        "status": "error",
        "message": (
            f"Report too large (limit {limit_mb} MB). Retake the photograph at a lower "
            "quality, or submit the report without it."
        ),
    }), 413


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "logirush-ner-platform"}), 200


def _warm_caches():
    """Load the model and build the first network assessment before anyone asks for it.

    Loading two persisted forests costs about a second and a half, and the first batch
    prediction pays NumPy's own warm-up on top. Left alone, that bill lands on whoever opens
    the dashboard first — which at a demo is the first thing anyone sees, and it reads as a
    slow product rather than a one-off cost. Doing it on a background thread at boot means
    the server is briefly busy while nobody is watching and instant once they are.

    Failure here is not fatal: it just means the first request warms the cache itself, which
    is exactly the behaviour this replaces.
    """
    try:
        from src.services.routing_service import routing_service

        started = time.time()
        routing_service.get_conditions(force=True)
        logger.info("Warmed prediction model and network assessment in %.2fs", time.time() - started)
    except Exception as e:  # pragma: no cover - depends on deployment environment
        logger.warning(f"Cache warm-up skipped: {e}")


def _warmup_wanted() -> bool:
    """Warm on a real server, stay out of the way everywhere else.

    Under pytest the suite swaps DATABASE_URL between modules, and a background thread
    holding a session against the previous one is a flaky test waiting to happen — for no
    benefit, since tests do not care how fast the first request is.
    """
    if os.environ.get("NER_DISABLE_WARMUP", "").strip().lower() in ("1", "true", "yes"):
        return False
    return "pytest" not in sys.modules


# Daemon thread: it must never hold up shutdown, and nothing waits on its result.
if _warmup_wanted():
    threading.Thread(target=_warm_caches, name="ner-warmup", daemon=True).start()


if __name__ == "__main__":
    # Debug mode costs real time on every request (the reloader re-imports the world on each
    # save, and the interactive debugger wraps every response), and it doubles start-up
    # because the reloader boots the app twice — warm-up included. It stays available for
    # development via FLASK_DEBUG=1, but it is not what someone running the demo wants.
    debug = os.environ.get("FLASK_DEBUG", "").strip().lower() in ("1", "true", "yes")
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=debug, host="0.0.0.0", port=port, threaded=True)