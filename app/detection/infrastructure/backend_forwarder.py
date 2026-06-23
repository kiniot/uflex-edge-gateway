"""Adapter that forwards detected items to the backend's therapy endpoints.

Translates the edge's outbox entries into the backend's REST contract and POSTs
them through the authenticated :class:`BackendClient` (the hybrid sign-in client
from §13.0.a). Idempotency is the backend's responsibility: it deduplicates on
the ``X-Edge-Sequence-Id`` header, so re-sending the same entry is safe.
"""
import logging

from app.detection.domain.entities import CompensatoryMovement, DetectedRepetition
from app.detection.infrastructure.repositories import OutboxEntry
from app.shared.infrastructure.backend_client import BackendClient

logger = logging.getLogger(__name__)

_CLASSIFICATION_TO_BACKEND = {
    "good": "Good",
    "incomplete": "Incomplete",
    "unsafe": "Unsafe",
}


def _format_recorded_at(recorded_at) -> str:
    """Format a datetime as the backend's ``yyyy-MM-dd HH:mm:ss.SSS`` (millis)."""
    return f"{recorded_at:%Y-%m-%d %H:%M:%S}.{recorded_at.microsecond // 1000:03d}"


def repetition_payload(rep: DetectedRepetition) -> dict:
    """Map a :class:`DetectedRepetition` to the ``recordRepetition`` request body."""
    return {
        "peakAngle": round(rep.peak_angle, 2),
        "achievedRom": round(rep.achieved_rom, 2),
        "classification": _CLASSIFICATION_TO_BACKEND[rep.classification],
        "recordedAt": _format_recorded_at(rep.recorded_at),
    }


def compensatory_payload(movement: CompensatoryMovement) -> dict:
    """Map a :class:`CompensatoryMovement` to the ``recordCompensatoryMovement`` body.

    The backend resource accepts only the discriminator; the timestamp and ids are
    edge-internal (the backend stamps its own time and dedupes on the header).
    """
    return {"type": movement.type}


class BackendForwarder:
    """Sends outbox entries to the backend, returning success per entry."""

    def __init__(self, client: BackendClient):
        self._client = client

    def forward(self, entry: OutboxEntry) -> bool:
        """Forward a single outbox entry. Returns ``True`` on a 2xx response.

        Never raises: auth/network/HTTP failures return ``False`` so the worker
        leaves the entry PENDING and retries later.
        """
        try:
            if entry.kind == "repetition":
                path = (f"/api/v1/therapy-sessions/{entry.session_id}"
                        f"/series/{entry.serie_id}/repetitions")
            elif entry.kind == "compensatory":
                path = f"/api/v1/therapy-sessions/{entry.session_id}/compensatory-movements"
            else:
                logger.error("Unknown outbox kind '%s' (entry %s)", entry.kind, entry.id)
                return False
            response = self._client.post(
                path,
                json=entry.payload,
                headers={"X-Edge-Sequence-Id": entry.edge_sequence_id},
            )
            if response.ok:
                return True
            logger.warning("Forward of entry %s -> HTTP %s", entry.id, response.status_code)
            return False
        except Exception as exc:  # noqa: BLE001 — never let a forward kill the worker
            logger.warning("Forward of entry %s failed: %s", entry.id, exc)
            return False
