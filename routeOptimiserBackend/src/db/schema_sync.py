"""Additive schema sync, so an existing database survives an upgrade.

`Base.metadata.create_all()` creates tables that do not exist. It does not touch tables that
do. That distinction is invisible until you ship a release that adds a column: the new tables
appear, everything looks fine at startup, and then every query against the *old* table dies
with "no such column" — on a screen, at a demo, rather than in the logs at boot.

That is exactly what happens upgrading from v5/v6 to v7: `users` and `auth_tokens` get
created, so signing in appears to work, while `incidents` is still missing `reported_by_id`
and half the verification trail.

This closes that gap for the only kind of change this project has actually made: columns
added to an existing table. It compares each model against the live table and issues
`ALTER TABLE ... ADD COLUMN` for whatever is missing.

It also widens a bounded VARCHAR to TEXT when the model has stopped declaring a length.
That is the one retype worth doing automatically, because it is the one that cannot be
noticed locally: SQLite does not enforce a declared length, so a column that has outgrown it
behaves perfectly on a developer's machine and rejects rows on PostgreSQL. `incidents.image_url`
is exactly that column — it holds a photograph as a base64 data URI.

Deliberately narrow otherwise. It does not rename, drop, narrow or backfill, and it is not a
substitute for Alembic if this project ever needs those — it is the smallest thing that stops
a routine upgrade from corrupting a running demo, and it says so out loud when it acts.
"""

import logging

from sqlalchemy import Text, inspect, text

logger = logging.getLogger("db")


def _sql_type(column, dialect):
    try:
        return column.type.compile(dialect=dialect)
    except Exception:
        # A type the dialect cannot render is not worth guessing at; TEXT holds anything and
        # SQLite is dynamically typed anyway.
        return "TEXT"


def _is_unbounded_text(column) -> bool:
    """Does the model declare this column with no length limit?"""
    return isinstance(column.type, Text) or (
        hasattr(column.type, "length") and column.type.length is None
    )


def _widen_columns(engine, metadata, inspector):
    """Retype bounded VARCHAR columns the models no longer bound.

    Only ever widens. A column that is already unbounded, or whose model still declares a
    length, is left exactly as it is. SQLite is skipped because it does not enforce the
    length in the first place — there is nothing to fix and no ALTER COLUMN to do it with.
    """
    dialect = engine.dialect.name
    if dialect == "sqlite":
        return []

    widened = []
    existing_tables = set(inspector.get_table_names())

    for table in metadata.sorted_tables:
        if table.name not in existing_tables:
            continue

        live = {col["name"]: col for col in inspector.get_columns(table.name)}
        for column in table.columns:
            current = live.get(column.name)
            if current is None or not _is_unbounded_text(column):
                continue
            if getattr(current["type"], "length", None) is None:
                continue  # already unbounded in the database

            if dialect == "mysql":
                ddl = f"ALTER TABLE `{table.name}` MODIFY `{column.name}` TEXT"
            else:
                ddl = (
                    f'ALTER TABLE "{table.name}" '
                    f'ALTER COLUMN "{column.name}" TYPE TEXT'
                )
            try:
                with engine.begin() as connection:
                    connection.execute(text(ddl))
                widened.append(f"{table.name}.{column.name}")
            except Exception as e:
                logger.warning(f"Could not widen {table.name}.{column.name} to TEXT: {e}")

    return widened


def sync_schema(engine, metadata):
    """Reconcile an existing database with the models: add missing columns, widen outgrown ones.

    Returns a list of "table.column" strings describing everything it changed.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added = []

    for table in metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all already made this one, in full

        present = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue

            # A NOT NULL column cannot be added to a table with existing rows unless it has a
            # default, so it is added as nullable. Nothing in this project relies on database
            # NOT NULL for a column introduced after the fact — the models enforce it.
            ddl = (
                f'ALTER TABLE "{table.name}" '
                f'ADD COLUMN "{column.name}" {_sql_type(column, engine.dialect)}'
            )
            try:
                with engine.begin() as connection:
                    connection.execute(text(ddl))
                added.append(f"{table.name}.{column.name}")
            except Exception as e:
                logger.warning(f"Could not add {table.name}.{column.name}: {e}")

    if added:
        logger.info(
            "Schema updated for an existing database — added: %s", ", ".join(added)
        )

    widened = _widen_columns(engine, metadata, inspect(engine))
    if widened:
        logger.info(
            "Schema updated for an existing database — widened to TEXT: %s", ", ".join(widened)
        )

    return added + widened
