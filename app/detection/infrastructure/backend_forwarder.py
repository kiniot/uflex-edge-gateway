"""Adapter that forwards detected items to the backend's therapy endpoints.

Translates the edge's outbox entries into the backend's REST contract and POSTs
them through the authenticated :class:`BackendClient` (the hybrid sign-in client
from §13.0.a). Idempotency is the backend's responsibility: it deduplicates on
the ``X-Edge-Sequence-Id`` header, so re-sending the same entry is safe.
"""
import logging
from enum import Enum

from app.detection.domain.entities import CompensatoryMovement, DetectedRepetition
from app.detection.infrastructure.repositories import OutboxEntry
from app.shared.infrastructure.backend_client import BackendClient

logger = logging.getLogger(__name__)

# 4xx statuses that are transient rather than a permanently-bad payload: auth (recoverable once the
# token/backend comes back), request timeout, and rate limiting. Everything else in the 4xx range is
# a permanent rejection for this entry (bad body, gone session, duplicate) -> quarantine it.
_TRANSIENT_CLIENT_STATUSES = {401, 408, 429}


class ForwardOutcome(Enum):
    """Result of forwarding one outbox entry, driving the worker's next action."""

    SENT = "sent"    # accepted by the backend -> mark SENT
    RETRY = "retry"  # transient failure -> keep PENDING, preserve FIFO, retry next cycle
    DROP = "drop"    # permanent rejection -> quarantine (mark FAILED) and skip so the queue advances

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

    def forward(self, entry: OutboxEntry) -> ForwardOutcome:
        """Forward a single outbox entry and classify the result.

        Never raises. Returns a :class:`ForwardOutcome`: ``SENT`` on 2xx; ``RETRY`` on a transient
        failure (5xx, network error, or a recoverable 4xx) so the entry stays PENDING; ``DROP`` on a
        permanent rejection (a non-transient 4xx or an unknown kind) so the worker quarantines it
        instead of retrying forever and blocking the FIFO queue behind it.
        """
        try:
            if entry.kind == "repetition":
                path = (f"/api/v1/therapy-sessions/{entry.session_id}"
                        f"/series/{entry.serie_id}/repetitions")
            elif entry.kind == "compensatory":
                path = f"/api/v1/therapy-sessions/{entry.session_id}/compensatory-movements"
            else:
                logger.error("Unknown outbox kind '%s' (entry %s) -> quarantining", entry.kind, entry.id)
                return ForwardOutcome.DROP
            response = self._client.post(
                path,
                json=entry.payload,
                headers={"X-Edge-Sequence-Id": entry.edge_sequence_id},
            )
            if response.ok:
                # Confirm compensations reaching the backend (low volume, unlike per-rep) so the
                # detected -> forwarded -> backend path is observable end to end during testing.
                if entry.kind == "compensatory":
                    logger.info("compensation forwarded to backend (serie=%s) -> HTTP %s",
                                entry.serie_id, response.status_code)
                return ForwardOutcome.SENT
            status = response.status_code
            if status >= 500 or status in _TRANSIENT_CLIENT_STATUSES:
                logger.warning("Forward of entry %s -> HTTP %s (transient, will retry)", entry.id, status)
                return ForwardOutcome.RETRY
            # Permanent 4xx (bad body, gone/cancelled session, duplicate): retrying never succeeds and
            # would block the whole FIFO queue, so quarantine this entry and let the queue advance.
            logger.warning(
                "Quarantining outbox entry %s (kind=%s) -> HTTP %s: rejected, skipping to unblock "
                "the queue", entry.id, entry.kind, status)
            return ForwardOutcome.DROP
        except Exception as exc:  # noqa: BLE001 — never let a forward kill the worker
            logger.warning("Forward of entry %s failed: %s (transient, will retry)", entry.id, exc)
            return ForwardOutcome.RETRY
