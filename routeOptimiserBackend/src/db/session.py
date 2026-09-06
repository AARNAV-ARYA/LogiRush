# src/db/session.py
"""
Database session management.

DATABASE_URL selects the backend:
    unset                       -> SQLite file at data/processed/ner_platform.db (local/demo)
    postgresql://... (or        -> PostgreSQL (production, e.g. Neon)
    postgres://...)

Render/Heroku-style providers hand out `postgres://` URLs, which SQLAlchemy 2.x no longer
accepts, so that prefix is rewritten to `postgresql://` here rather than making deployment
config a footgun.
"""

import logging
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.db.models import Base

logger = logging.getLogger("db")

_engine = None
_SessionLocal = None


def _default_sqlite_url() -> str:
    data_dir = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "processed")
    )
    os.makedirs(data_dir, exist_ok=True)
    return f"sqlite:///{os.path.join(data_dir, 'ner_platform.db')}"


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return _default_sqlite_url()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def get_engine():
    global _engine
    if _engine is None:
        url = get_database_url()
        kwargs = {"future": True, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            # Flask serves requests on multiple threads; SQLite needs this to be shared.
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs.pop("pool_pre_ping")
        _engine = create_engine(url, **kwargs)
        logger.info(f"Database engine created ({url.split('://')[0]}).")
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionLocal


def get_session():
    return get_session_factory()()


def init_db():
    """Create missing tables, then reconcile columns on the ones that already exist.

    The second half matters as much as the first. create_all() never alters an existing
    table, so upgrading a database that predates a new column leaves it silently broken —
    see src/db/schema_sync.py.
    """
    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    from src.db.schema_sync import sync_schema

    sync_schema(engine, Base.metadata)
    logger.info("Database tables ensured.")
