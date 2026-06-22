"""Shared database infrastructure for the uFlex Edge Gateway.

Provides a single :class:`peewee.SqliteDatabase` instance (``db``) imported by
ORM models across bounded contexts. WAL + a busy timeout let the Flask request
thread (sample ingest / outbox enqueue) and the forwarding worker thread share
the database without "database is locked" errors; Peewee opens one connection
per thread automatically.

The edge persists only ``devices`` (kit auth) and ``outbox`` (items pending
forwarding); raw samples live in memory and the series result is owned by the
backend.
"""
from peewee import SqliteDatabase

# Shared SQLite database instance. WAL improves concurrent read/write across the
# Flask and worker threads; busy_timeout waits out brief write locks.
db = SqliteDatabase('uflex_edge.db', pragmas={'journal_mode': 'wal', 'busy_timeout': 5000})


def init_db() -> None:
    """Open a connection and create the ``devices`` and ``outbox`` tables if absent.

    Idempotent (``safe=True``). Deferred imports avoid circular dependencies at
    module load.
    """
    db.connect(reuse_if_open=True)
    from iam.infrastructure.models import Device
    from monitoring.infrastructure.models import OutboxItem
    db.create_tables([Device, OutboxItem], safe=True)
    db.close()
