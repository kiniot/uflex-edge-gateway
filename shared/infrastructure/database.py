"""Shared database infrastructure for the uFlex Edge Gateway.

Provides a single :class:`peewee.SqliteDatabase` instance (``db``) that is
imported by ORM models across all bounded contexts, ensuring every model
operates on the same physical database file.

The :func:`init_db` helper is called once at application start-up to open a
connection and create any missing tables without affecting existing data
(``safe=True``).

Note:
    The ``db`` object itself is not connected until :func:`init_db` is
    called.  Peewee's ``SqliteDatabase`` manages the connection lifecycle
    via its own thread-local storage.
"""
from peewee import SqliteDatabase

# Shared SQLite database instance used by all bounded-context ORM models.
db = SqliteDatabase('uflex_edge.db')


def init_db() -> None:
    """Open the database connection and create all required tables.

    Imports the ORM models from the IAM and Monitoring bounded contexts at
    call time (deferred import) to avoid circular dependencies during module
    loading, then issues a ``CREATE TABLE IF NOT EXISTS`` for each model.

    This function is idempotent: calling it when the tables already exist is
    safe and has no side-effects (``safe=True`` suppresses ``CREATE TABLE``
    errors for pre-existing tables).

    Side effects:
        - Opens a connection to ``uflex_edge.db`` (creating the file if it
          does not exist).
        - Creates the ``devices`` table if absent.
        - Creates the ``movement_records`` table if absent.
        - Closes the connection after table creation.
    """
    db.connect()
    from iam.infrastructure.models import Device
    from monitoring.infrastructure.models import MovementRecord, SerieExecution
    db.create_tables([Device, MovementRecord, SerieExecution], safe=True)
    _migrate_movement_records_serie_id()
    db.close()


def _migrate_movement_records_serie_id() -> None:
    """Add ``movement_records.serie_id`` to pre-existing databases if missing.

    ``create_tables(safe=True)`` only creates absent tables; it does not alter an
    existing one.  Databases created before the ``serie_id`` column was added
    therefore lack it, which would break inserts.  This issues an idempotent
    ``ALTER TABLE ... ADD COLUMN`` only when the column is not already present.
    """
    columns = {row[1] for row in db.execute_sql("PRAGMA table_info(movement_records)")}
    if "serie_id" not in columns:
        db.execute_sql("ALTER TABLE movement_records ADD COLUMN serie_id VARCHAR")
