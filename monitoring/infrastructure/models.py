"""Peewee ORM model for the Monitoring bounded context.

The edge persists only what must survive a restart: the **outbox** of detected
items pending forwarding to the backend. Raw samples are a transient in-memory
window (not a durable table), and the per-serie execution result is owned by the
backend — so neither is stored here.
"""
from peewee import Model, AutoField, CharField, TextField, DateTimeField

from shared.infrastructure.database import db


class OutboxItem(Model):
    """ORM mapping for the ``outbox`` table.

    A durable queue of items the edge has detected and must forward to the
    backend idempotently. Survives restarts so a transient network outage never
    loses a repetition.

    Attributes:
        id (AutoField): Insertion order — drives FIFO flush.
        kind (CharField): ``'repetition'`` | ``'compensatory'`` — selects the
            backend endpoint.
        serial_number (CharField): Kit the item belongs to.
        session_id (CharField): Backend therapy session (URL path).
        serie_id (CharField): Backend serie within the session (URL path).
        edge_sequence_id (CharField): Idempotency key (UUID), sent as the
            ``X-Edge-Sequence-Id`` header; the backend deduplicates on it.
        payload (TextField): JSON body to POST, ready to send.
        forward_status (CharField): ``'PENDING'`` | ``'SENT'``.
        created_at (DateTimeField): When the item was enqueued (UTC).
    """

    id = AutoField()
    kind = CharField()
    serial_number = CharField()
    session_id = CharField()
    serie_id = CharField()
    edge_sequence_id = CharField()
    payload = TextField()
    forward_status = CharField(default="PENDING")
    created_at = DateTimeField()

    class Meta:
        """Peewee metadata: binds the model to the shared database and names the table."""

        database = db
        table_name = 'outbox'
