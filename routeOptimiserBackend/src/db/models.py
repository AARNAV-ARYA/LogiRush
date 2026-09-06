# src/db/models.py
"""
Database models for community incident reporting and shipment records (SIH Module 5).

Uses SQLAlchemy so the same models run on SQLite locally (zero setup, good for a demo or an
offline field laptop) and on PostgreSQL in production, selected purely by the DATABASE_URL
environment variable. No raw SQL, no engine-specific column types.

Note on `client_uuid`: offline clients (Module 6) generate a UUID when a report is created on
the device, before it can reach the server. That UUID is UNIQUE here, which is what makes
sync idempotent — replaying a queued report that already landed is a no-op rather than a
duplicate. This is the single most important field for offline correctness.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

INCIDENT_TYPES = ["landslide", "flood", "road_block", "bridge_damage", "accident", "other"]

# Where a report came in from. Recorded, never inferred: an unmarked caller is "api", not a
# guess at whichever client is more common.
REPORT_SOURCES = ["app", "web", "api"]
# The lifecycle of a report.
#
#   unverified  as submitted; raises risk but never closes a road on its own
#   verified    a human confirmed it; a severe blocking one closes its corridor
#   rejected    a human judged it wrong; contributes nothing
#   resolved    it happened and it is over — the slip is cleared, the water has gone down
#   withdrawn   the reporter took it back before anyone acted on it
#
# `resolved` is the state this system was missing. Incidents are events, not properties of a
# road: a landslide cleared on Tuesday should reopen the corridor on Tuesday, not linger until
# the seven-day window happens to expire. Without it the only way to reopen a road early was
# to delete the report or mark it rejected, and both are lies — one destroys the record of a
# real event, the other says it never happened. Resolving keeps the history and frees the road.
VERIFICATION_STATUSES = [
    "unverified",
    "awaiting_countersign",
    "verified",
    "rejected",
    "resolved",
    "withdrawn",
]

# Statuses that still bear on routing. Anything outside this set is inert: it stays in the
# record and the audit trail, and stops affecting a single score.
# `awaiting_countersign` is deliberately active but not blocking: one verifier's judgement is
# enough to raise a corridor's risk, and not enough to shut it.
ACTIVE_STATUSES = {"unverified", "awaiting_countersign", "verified"}


def _utcnow():
    return datetime.now(timezone.utc)


def _iso(value):
    """Serialise a timestamp with an explicit offset, always.

    Every timestamp here is written as UTC. SQLite has no timezone type, so it hands those
    values back *naive* — and a naive ISO string on the wire is not UTC to a client, it is
    local time. Both the web console and the field app parse these with `new Date(...)`, so a
    report filed one minute ago in Kolkata rendered as "5 h ago" in the review queue, which is
    the one property a verifier judges a report by. PostgreSQL keeps the offset and never
    showed this, which is why it survived: the bug lives only on the SQLite path, which is
    every local run and every demo.

    Stamping UTC on a naive value is safe precisely because nothing here ever writes local
    time — see `_utcnow`, and the ISO parsing in the incident endpoint, which assumes UTC for
    an offset-less input for the same reason.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Client-generated UUID; unique so replayed offline submissions de-duplicate.
    client_uuid = Column(String(64), unique=True, index=True, nullable=False)

    incident_type = Column(String(32), nullable=False, index=True)
    # 1 (minor) to 5 (severe). Kept numeric so it can feed risk maths directly.
    severity = Column(Integer, nullable=False, default=3)
    description = Column(Text, nullable=True)

    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    # Nearest road segment, resolved server-side at ingest time (deterministic, not ML).
    # Null when the report is off-network: no modelled corridor is close enough for the
    # attribution to mean anything, so none is claimed.
    segment_id = Column(String(32), nullable=True, index=True)
    # How far the report actually was from that corridor. Stored because "attributed to
    # RS004" reads as certainty; "attributed to RS004, 0.6 km away" reads as evidence, and
    # 41 km away tells an operator to look again before anyone acts on it.
    segment_distance_km = Column(Float, nullable=True)

    # Text, not a bounded VARCHAR. Both clients attach a downscaled photograph as a base64
    # data URI, which is tens of thousands of characters — far past any VARCHAR(n) worth
    # declaring. SQLite ignores the declared length, so a bounded column looks fine locally
    # and then rejects every photographed report the moment the same code runs on the
    # PostgreSQL database the web console and the field app actually share.
    image_url = Column(Text, nullable=True)
    reporter_name = Column(String(128), nullable=True)
    reporter_contact = Column(String(128), nullable=True)

    # Which client filed it: "app" (NER Field Reporter), "web" (the console form), or "api"
    # for a direct call. Both clients write to this one table, and a verifier reviewing a
    # queue of reports should be able to see that a report came from a phone at the
    # obstruction rather than from someone at a desk — the two deserve different weight.
    source = Column(String(16), nullable=False, default="api", index=True)

    # Verification is a deterministic human/admin action per the AI Usage Policy — never ML.
    verification_status = Column(String(24), nullable=False, default="unverified", index=True)

    # Who filed it. Null for an anonymous submission, which stays permitted — a stranded
    # driver with no account is exactly who this platform needs to hear from. When it IS
    # set, it is what makes "you cannot verify your own report" enforceable.
    reported_by_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Verification provenance. Kept as both id and username so the record stays readable
    # after an account is deactivated or renamed.
    verified_by_id = Column(Integer, nullable=True)
    verified_by_username = Column(String(64), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)

    # The second signature on a closure. Until this is filled the status is
    # `awaiting_countersign` and the corridor stays open.
    countersigned_by_id = Column(Integer, nullable=True)
    countersigned_by_username = Column(String(64), nullable=True)

    # Why it ended. For `resolved`, what cleared it; for `rejected`, why it was not real.
    resolution_note = Column(Text, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    # reported_at = when it happened on the device (preserved across offline sync).
    # created_at  = when the server first stored it.
    reported_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "client_uuid": self.client_uuid,
            "type": self.incident_type,
            "severity": self.severity,
            "description": self.description,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "segment_id": self.segment_id,
            "segment_distance_km": self.segment_distance_km,
            "image_url": self.image_url,
            "reporter_name": self.reporter_name,
            "reporter_contact": self.reporter_contact,
            # Rows written before this column existed have no source; "unknown" is the
            # honest answer there, and never a guess at "web".
            "source": self.source or "unknown",
            "verification_status": self.verification_status,
            "reported_by_id": self.reported_by_id,
            "verified_by": self.verified_by_username,
            "verified_at": _iso(self.verified_at),
            "countersigned_by": self.countersigned_by_username,
            "resolution_note": self.resolution_note,
            "resolved_at": _iso(self.resolved_at),
            "reported_at": _iso(self.reported_at),
            "created_at": _iso(self.created_at),
        }


class Shipment(Base):
    __tablename__ = "shipments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_uuid = Column(String(64), unique=True, index=True, nullable=True)

    origin_id = Column(String(32), nullable=False)
    destination_id = Column(String(32), nullable=False)
    cargo_type = Column(String(32), nullable=False, default="general")
    urgency = Column(String(16), nullable=False, default="normal")
    weight_kg = Column(Float, nullable=True)
    priority = Column(Integer, nullable=True)

    status = Column(String(24), nullable=False, default="planned", index=True)
    # Snapshot of the route returned at planning time, stored as JSON text so the record
    # stays meaningful even after conditions change and the route would be recalculated.
    planned_route_json = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "client_uuid": self.client_uuid,
            "origin_id": self.origin_id,
            "destination_id": self.destination_id,
            "cargo_type": self.cargo_type,
            "urgency": self.urgency,
            "weight_kg": self.weight_kg,
            "priority": self.priority,
            "status": self.status,
            "created_at": _iso(self.created_at),
        }


# ---------------------------------------------------------------------------- access control

ROLES = ["reporter", "verifier", "controller"]

# What a verified, severe, blocking report actually does: it removes a corridor from the
# graph, so a convoy physically cannot be routed through it. That is a real operational
# decision with a cost attached either way — a wrong closure strands a district, a missed
# one drives a truck into a landslide. It is therefore the one action in this system that
# requires a second, different verifier to countersign before it takes effect.
COUNTERSIGN_SEVERITY = 5
COUNTERSIGN_TYPES = {"landslide", "road_block", "bridge_damage", "flood"}


class User(Base):
    """An operator of the platform.

    Deliberately thin. This is an authorisation model, not an identity provider: there is no
    email verification, password reset or session management here, because in deployment
    these accounts would come from the state's existing directory (a DDMA or ASDMA roster),
    not be created in this application. What the platform must own is the *mapping* from a
    person to what they may decide, and that is what this table is.
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    full_name = Column(String(128), nullable=False)
    # PBKDF2 via werkzeug; never a plaintext or reversible form.
    password_hash = Column(String(256), nullable=False)

    role = Column(String(16), nullable=False, default="reporter", index=True)
    organisation = Column(String(128), nullable=True)

    # Comma-separated state names a verifier may act in. Empty means "no jurisdiction",
    # which for a verifier means they can verify nothing — a safer default than everything.
    # Controllers ignore this field entirely.
    jurisdiction = Column(String(256), nullable=True)

    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    def states(self) -> list:
        if not self.jurisdiction:
            return []
        return [s.strip() for s in self.jurisdiction.split(",") if s.strip()]

    def may_act_in(self, state: str | None) -> bool:
        """Controllers act anywhere. Verifiers act only inside their assigned states.

        An incident whose state could not be resolved returns False for a verifier: an
        unplaceable report is escalated to a controller rather than being open to whoever
        happens to see it first.
        """
        if self.role == "controller":
            return True
        if self.role != "verifier":
            return False
        return bool(state) and state in self.states()

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "full_name": self.full_name,
            "role": self.role,
            "organisation": self.organisation,
            "jurisdiction": self.states(),
            "active": self.active,
        }


class AuthToken(Base):
    """A bearer token issued at login.

    Opaque and stored, rather than a self-contained JWT, for one reason that matters in this
    domain: a token that turns out to belong to a compromised or reassigned account has to be
    revocable *now*. A stateless JWT stays valid until it expires no matter what the roster
    says, and "wait for it to lapse" is not an answer when the token can close roads.
    """

    __tablename__ = "auth_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    user = relationship("User")


class IncidentAudit(Base):
    """Who did what to a report, and why.

    Every state change is appended here and nothing is ever updated in place. A verification
    that closed a highway has to be answerable months later — including, especially, a
    deletion, which is why the audit row survives the incident it describes.
    """

    __tablename__ = "incident_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    incident_id = Column(Integer, nullable=False, index=True)
    action = Column(String(24), nullable=False)          # verify | reject | resolve | withdraw | delete | countersign
    from_status = Column(String(16), nullable=True)
    to_status = Column(String(16), nullable=True)
    actor_id = Column(Integer, nullable=True)
    actor_username = Column(String(64), nullable=True)
    actor_role = Column(String(16), nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "incident_id": self.incident_id,
            "action": self.action,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "actor": self.actor_username,
            "actor_role": self.actor_role,
            "reason": self.reason,
            "at": _iso(self.created_at),
        }
