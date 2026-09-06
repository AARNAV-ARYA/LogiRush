# tests/test_data_sources.py
"""Tests for the data provenance manifest.

The manifest exists to stop the platform overstating itself, so what is worth pinning is not
its shape but its honesty: that nothing synthetic is labelled live, that the inputs a judge
will ask about (rainfall, the model, incident reports) are each described, and that the claim
served to the UI still matches the code that loads the data.
"""

import os
import tempfile

import pytest


@pytest.fixture(scope="module")
def client():
    tmp_dir = tempfile.mkdtemp()
    os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmp_dir, 'sources.db')}"

    import src.db.session as session_module

    session_module._engine = None
    session_module._SessionLocal = None
    session_module.init_db()

    from main import app

    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def _manifest(client):
    response = client.get("/api/ner/data-sources")
    assert response.status_code == 200
    return response.get_json()


def test_every_source_declares_a_trust_level(client):
    from src.data_processing.data_sources import TRUST_LEVELS

    for source in _manifest(client)["sources"]:
        assert source["trust"] in TRUST_LEVELS, source["id"]
        assert source["origin"] and source["summary"]


def test_rainfall_is_never_presented_as_an_imd_feed(client):
    """The single most tempting overstatement in this project: the model consumes a field
    called forecast_rainfall_mm_48h, and a screen showing it looks exactly like a screen
    showing IMD's forecast. The manifest has to say the difference out loud."""
    rainfall = next(s for s in _manifest(client)["sources"] if s["id"] == "rainfall")

    assert rainfall["trust"] == "sample"
    assert "IMD" in rainfall["upstream"]["name"]
    # It must name IMD only as what would replace it, never as where it comes from.
    assert "IMD" not in rainfall["origin"]
    assert "NOT an IMD feed" in rainfall["summary"]


def test_the_model_is_marked_synthetic_and_scoped(client):
    model = next(s for s in _manifest(client)["sources"] if s["id"] == "disaster_model")
    assert model["trust"] == "synthetic"
    assert "not validated forecasts" in model["caveat"]


def test_incident_reports_are_the_live_input_and_count_both_clients(client):
    """Reports are the one genuinely real input, and the manifest reports the live database
    — which is also what makes it a usable check that the app and console share one."""
    from uuid import uuid4

    for source in ("app", "web"):
        client.post("/api/ner/incidents", json={
            "client_uuid": str(uuid4()), "type": "flood", "severity": 2,
            "latitude": 26.14, "longitude": 91.73, "source": source,
        })

    incidents = next(s for s in _manifest(client)["sources"] if s["id"] == "incident_reports")
    assert incidents["trust"] == "live"
    assert incidents["live_stats"]["total"] >= 2
    assert incidents["live_stats"]["by_source"]["app"] >= 1
    assert incidents["live_stats"]["by_source"]["web"] >= 1


def test_the_headline_refuses_the_official_data_claim(client):
    headline = _manifest(client)["headline"]
    for authority in ("IMD", "GSI", "CWC", "ASDMA"):
        assert authority in headline
    assert "nothing here is an official" in headline


def test_file_backed_sources_point_at_files_that_exist(client):
    """A manifest that names a file the repository does not ship is worse than no manifest."""
    for source in _manifest(client)["sources"]:
        storage = source.get("storage")
        if isinstance(storage, dict) and "file" in storage:
            assert storage["present"] is True, source["id"]


def test_widening_is_a_no_op_on_sqlite(client):
    """SQLite does not enforce a declared length, so there is nothing to widen and no
    ALTER COLUMN to do it with. The retype exists for the PostgreSQL database the two
    clients actually share."""
    from sqlalchemy import inspect

    from src.db.models import Base
    from src.db.schema_sync import _widen_columns
    from src.db.session import get_engine

    engine = get_engine()
    assert _widen_columns(engine, Base.metadata, inspect(engine)) == []


def test_unbounded_text_is_recognised_by_declaration_not_by_name():
    from src.db.models import Incident

    from src.db.schema_sync import _is_unbounded_text

    assert _is_unbounded_text(Incident.__table__.c.image_url) is True
    assert _is_unbounded_text(Incident.__table__.c.description) is True
    assert _is_unbounded_text(Incident.__table__.c.reporter_name) is False
