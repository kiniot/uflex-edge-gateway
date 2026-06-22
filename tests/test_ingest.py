"""Integration-ish tests for the ingest pipeline (sample -> detector -> outbox)."""
from app.detection.application.services import SampleIngestService
from app.detection.application.state import EdgeRuntimeState
from app.detection.domain.entities import ExecutionContext
from app.detection.infrastructure.repositories import OutboxRepository

KIT = "uflex-kit-001"


def test_completed_rep_is_enqueued_for_forwarding(memory_db):
    state = EdgeRuntimeState()
    state.update_context(KIT, ExecutionContext(
        session_id="sess-1", serie_id="ser-1", target_rom=80, max_safe_angle=95))
    service = SampleIngestService(state, OutboxRepository())

    for angle in [0, 90, 0]:
        service.ingest(KIT, angle, None)

    pending = OutboxRepository().find_pending()
    assert len(pending) == 1
    entry = pending[0]
    assert entry.kind == "repetition"
    assert entry.session_id == "sess-1" and entry.serie_id == "ser-1"
    assert entry.payload["classification"] == "Good"
    assert entry.edge_sequence_id  # a UUID idempotency key was assigned


def test_samples_without_active_context_are_ignored(memory_db):
    state = EdgeRuntimeState()  # no context set
    service = SampleIngestService(state, OutboxRepository())

    for angle in [0, 90, 0]:
        service.ingest(KIT, angle, None)

    assert OutboxRepository().count_pending() == 0
