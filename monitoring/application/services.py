"""Application services for the Monitoring bounded context.

Orchestrate the edge's real-time use-cases on top of the in-memory runtime state:
ingesting a sample (feed the detector, enqueue any completed repetition) and a
read-only debug view over the transient window. Cross-context kit authentication
is enforced at the interface boundary (IAM), so these services do not depend on
IAM infrastructure.
"""
import uuid

from monitoring.application.state import EdgeRuntimeState
from monitoring.domain.entities import DetectedRepetition
from monitoring.domain.services import build_sample, window_summary as compute_window_summary
from monitoring.infrastructure.backend_forwarder import repetition_payload
from monitoring.infrastructure.repositories import OutboxRepository


class SampleIngestService:
    """Ingest one movement sample and enqueue any repetition it completes.

    Validates and buffers the sample, feeds it to the active detector, and — when
    a flex-and-return cycle closes — builds a :class:`DetectedRepetition` (with a
    fresh idempotency UUID) and appends it to the durable outbox for forwarding.
    """

    def __init__(self, state: EdgeRuntimeState, outbox_repo: OutboxRepository = None):
        self._state = state
        self._outbox = outbox_repo or OutboxRepository()

    def ingest(self, serial_number: str, angle, created_at):
        """Process a sample; returns the built :class:`MovementSample`.

        Raises:
            ValueError: On invalid angle/timestamp (mapped to 400 at the interface).
        """
        sample = build_sample(serial_number, angle, created_at)
        rep, context = self._state.ingest_sample(serial_number, sample)
        if rep and context:
            self._enqueue_repetition(serial_number, context, rep, sample.recorded_at)
        return sample

    def _enqueue_repetition(self, serial_number, context, rep, recorded_at):
        detected = DetectedRepetition(
            serial_number=serial_number,
            session_id=context.session_id,
            serie_id=context.serie_id,
            edge_sequence_id=str(uuid.uuid4()),
            achieved_rom=rep["achieved_rom"],
            peak_angle=rep["peak_angle"],
            classification=rep["classification"],
            met_target=rep["met_target"],
            unsafe=rep["unsafe"],
            recorded_at=recorded_at,
        )
        self._outbox.enqueue(
            "repetition", serial_number, context.session_id, context.serie_id,
            detected.edge_sequence_id, repetition_payload(detected),
        )


class DebugViewService:
    """Read-only live view over the in-memory window (diagnostics / demo)."""

    def __init__(self, state: EdgeRuntimeState):
        self._state = state

    def window_summary(self, serial_number: str) -> dict:
        summary = compute_window_summary(self._state.window(serial_number))
        summary["serial_number"] = serial_number
        context = self._state.context(serial_number)
        summary["active_serie_id"] = context.serie_id if context else None
        return summary

    def recent_samples(self, serial_number: str, limit: int = 100) -> list[dict]:
        samples = self._state.window(serial_number)[-limit:]
        return [
            {
                "serial_number": s.serial_number,
                "angle": s.angle,
                "recorded_at": s.recorded_at.isoformat(),
            }
            for s in samples
        ]
