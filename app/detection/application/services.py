"""Application services for the Detection bounded context.

Orchestrate the edge's real-time use-cases on top of the in-memory runtime state:
ingesting a sample (feed the detector, enqueue any completed repetition) and a
read-only debug view over the transient window. Cross-context kit authentication
is enforced at the interface boundary (IAM), so these services do not depend on
IAM infrastructure.
"""
import uuid

from app.detection.application.state import EdgeRuntimeState
from app.detection.domain.entities import DetectedRepetition
from app.detection.domain.services import build_sample, normalize_joint, window_summary as compute_window_summary
from app.detection.infrastructure.backend_forwarder import repetition_payload
from app.detection.infrastructure.repositories import OutboxRepository


class SampleIngestService:
    """Ingest one movement sample and enqueue any repetition it completes.

    Validates and buffers the sample, feeds it to the active detector, and — when
    a flex-and-return cycle closes — builds a :class:`DetectedRepetition` (with a
    fresh idempotency UUID) and appends it to the durable outbox for forwarding.
    """

    def __init__(self, state: EdgeRuntimeState, outbox_repo: OutboxRepository = None):
        self._state = state
        self._outbox = outbox_repo or OutboxRepository()

    def ingest(self, serial_number: str, angle, created_at, proximal=None):
        """Process one sample; returns the built :class:`MovementSample`.

        Raises:
            ValueError: On invalid angle/timestamp (mapped to 400 at the interface).
        """
        sample = build_sample(serial_number, angle, created_at, proximal)
        rep, context = self._state.ingest_sample(serial_number, sample)
        if rep and context:
            self._enqueue_repetition(serial_number, context, rep, sample.recorded_at)
        return sample

    def ingest_batch(self, serial_number: str, samples: list) -> list:
        """Ingest a batch of samples in order (same semantics as N sequential posts).

        Each item is ``{"target_angle", "proximal_signal"?, "recorded_at"?}``. The
        firmware omits ``recorded_at`` (no RTC) so the edge stamps on receipt;
        ordering is preserved by the array.

        Raises:
            ValueError: On the first invalid angle/timestamp.
        """
        return [
            self.ingest(serial_number, s.get("target_angle"),
                        s.get("recorded_at"), s.get("proximal_signal"))
            for s in samples
        ]

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

    def active_context(self, serial_number: str) -> dict:
        """Return the kit's active serie context for the firmware down-channel.

        Shape: ``{serial_number, active_joint, max_safe_angle, serie_id}`` with
        nulls when no serie is active. ``active_joint`` is the normalized joint
        enum (ELBOW/WRIST) the firmware maps to an IMU pair.
        """
        context = self._state.context(serial_number)
        return {
            "serial_number": serial_number,
            "active_joint": normalize_joint(context.body_part) if context else None,
            "max_safe_angle": context.max_safe_angle if context else None,
            "serie_id": context.serie_id if context else None,
        }

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
