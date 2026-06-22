"""Repository for the Monitoring outbox.

Persists items pending forwarding to the backend and reconstructs them as plain
:class:`OutboxEntry` objects, keeping the application and forwarding layers free
of ORM and database details.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from monitoring.infrastructure.models import OutboxItem as OutboxItemModel


@dataclass
class OutboxEntry:
    """A durable, ready-to-send outbox item (ORM-free view)."""

    id: int
    kind: str
    serial_number: str
    session_id: str
    serie_id: str
    edge_sequence_id: str
    payload: dict
    forward_status: str


def _to_entry(model: OutboxItemModel) -> OutboxEntry:
    return OutboxEntry(
        id=model.id,
        kind=model.kind,
        serial_number=model.serial_number,
        session_id=model.session_id,
        serie_id=model.serie_id,
        edge_sequence_id=model.edge_sequence_id,
        payload=json.loads(model.payload),
        forward_status=model.forward_status,
    )


class OutboxRepository:
    """Durable FIFO queue of items pending forwarding to the backend."""

    @staticmethod
    def enqueue(kind: str, serial_number: str, session_id: str, serie_id: str,
                edge_sequence_id: str, payload: dict) -> OutboxEntry:
        """Append a PENDING item; ``payload`` is the exact JSON body to POST."""
        row = OutboxItemModel.create(
            kind=kind,
            serial_number=serial_number,
            session_id=session_id,
            serie_id=serie_id,
            edge_sequence_id=edge_sequence_id,
            payload=json.dumps(payload),
            forward_status="PENDING",
            created_at=datetime.now(timezone.utc),
        )
        return _to_entry(row)

    @staticmethod
    def find_pending(limit: int = 50) -> list[OutboxEntry]:
        """Return PENDING items in insertion (FIFO) order."""
        query = (OutboxItemModel
                 .select()
                 .where(OutboxItemModel.forward_status == "PENDING")
                 .order_by(OutboxItemModel.id.asc())
                 .limit(limit))
        return [_to_entry(row) for row in query]

    @staticmethod
    def mark_sent(entry_id: int) -> None:
        """Mark an item as successfully forwarded."""
        (OutboxItemModel
         .update(forward_status="SENT")
         .where(OutboxItemModel.id == entry_id)
         .execute())

    @staticmethod
    def count_pending() -> int:
        """Return how many items are still pending (diagnostics)."""
        return (OutboxItemModel
                .select()
                .where(OutboxItemModel.forward_status == "PENDING")
                .count())
