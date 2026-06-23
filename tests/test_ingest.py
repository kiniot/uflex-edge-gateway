"""Integration-ish tests for the ingest pipeline (sample -> detector -> outbox)."""
from app.detection.application.progress_broker import ProgressBroker
from app.detection.application.services import DebugViewService, SampleIngestService
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


def test_batch_detects_rep(memory_db):
    state = EdgeRuntimeState()
    state.update_context(KIT, ExecutionContext(
        session_id="sess-1", serie_id="ser-1", target_rom=80, max_safe_angle=95))
    service = SampleIngestService(state, OutboxRepository())

    service.ingest_batch(KIT, [
        {"target_angle": 0, "proximal_signal": 1.0},
        {"target_angle": 90, "proximal_signal": 2.0},
        {"target_angle": 0, "proximal_signal": 3.0},
    ])

    pending = OutboxRepository().find_pending()
    assert len(pending) == 1
    assert pending[0].payload["classification"] == "Good"


def test_batch_preserves_proximal_signal(memory_db):
    state = EdgeRuntimeState()
    state.update_context(KIT, ExecutionContext(
        session_id="s", serie_id="r", target_rom=80, max_safe_angle=95))
    service = SampleIngestService(state, OutboxRepository())

    service.ingest_batch(KIT, [{"target_angle": 30, "proximal_signal": 12.5}])

    assert state.window(KIT)[-1].proximal_signal == 12.5


def test_malformed_proximal_does_not_reject_sample(memory_db):
    state = EdgeRuntimeState()
    state.update_context(KIT, ExecutionContext(
        session_id="s", serie_id="r", target_rom=80, max_safe_angle=95))
    service = SampleIngestService(state, OutboxRepository())

    sample = service.ingest(KIT, 30, None, proximal="not-a-number")

    assert sample.angle == 30
    assert sample.proximal_signal is None


def test_active_context_normalizes_joint():
    state = EdgeRuntimeState()
    state.update_context(KIT, ExecutionContext(
        session_id="s", serie_id="r", target_rom=80, movement_type="FLEXION",
        body_part="elbow", max_safe_angle=95))

    ctx = DebugViewService(state).active_context(KIT)

    assert ctx == {"serial_number": KIT, "active_joint": "ELBOW",
                   "max_safe_angle": 95, "serie_id": "r"}


def test_active_context_no_serie_returns_nulls():
    ctx = DebugViewService(EdgeRuntimeState()).active_context(KIT)

    assert ctx == {"serial_number": KIT, "active_joint": None,
                   "max_safe_angle": None, "serie_id": None}


def test_completed_rep_publishes_progress_event(memory_db):
    state = EdgeRuntimeState()
    state.update_context(KIT, ExecutionContext(
        session_id="sess-1", serie_id="ser-1", target_rom=80, max_safe_angle=95))
    broker = ProgressBroker()
    q = broker.subscribe(KIT)
    service = SampleIngestService(state, OutboxRepository(), broker)

    for angle in [0, 90, 0]:
        service.ingest(KIT, angle, None)

    event = q.get_nowait()
    assert event["serie_id"] == "ser-1"
    assert event["reps_detected"] == 1
    assert event["classification"] == "good"  # lowercase, not the backend casing


def test_serie_change_resets_progress_tally(memory_db):
    state = EdgeRuntimeState()
    broker = ProgressBroker()
    q = broker.subscribe(KIT)
    service = SampleIngestService(state, OutboxRepository(), broker)

    state.update_context(KIT, ExecutionContext(
        session_id="s", serie_id="ser-A", target_rom=80, max_safe_angle=95))
    for angle in [0, 90, 0]:
        service.ingest(KIT, angle, None)
    assert q.get_nowait()["reps_detected"] == 1

    state.update_context(KIT, ExecutionContext(
        session_id="s", serie_id="ser-B", target_rom=80, max_safe_angle=95))
    for angle in [0, 90, 0]:
        service.ingest(KIT, angle, None)
    assert q.get_nowait()["reps_detected"] == 1  # reset, not 2


def test_compensation_is_enqueued_for_forwarding(memory_db):
    state = EdgeRuntimeState()
    state.update_context(KIT, ExecutionContext(
        session_id="sess-1", serie_id="ser-1", target_rom=80, max_safe_angle=95))
    service = SampleIngestService(state, OutboxRepository())

    # angle stalled, proximal sweeping -> compensation over a full window
    for i in range(20):
        service.ingest(KIT, 30.0, None, proximal=(0.0 if i % 2 == 0 else 20.0))

    comp = [e for e in OutboxRepository().find_pending() if e.kind == "compensatory"]
    assert len(comp) == 1
    assert comp[0].payload == {"type": "ShoulderCompensation"}
    assert comp[0].edge_sequence_id


def test_normal_rep_enqueues_only_repetition_not_compensation(memory_db):
    state = EdgeRuntimeState()
    state.update_context(KIT, ExecutionContext(
        session_id="s", serie_id="r", target_rom=80, max_safe_angle=95))
    service = SampleIngestService(state, OutboxRepository())

    for angle in [0, 90, 0]:
        service.ingest(KIT, angle, None, proximal=5.0)  # proximal flat -> no compensation

    assert [e.kind for e in OutboxRepository().find_pending()] == ["repetition"]


def test_compensation_without_proximal_enqueues_nothing(memory_db):
    state = EdgeRuntimeState()
    state.update_context(KIT, ExecutionContext(
        session_id="s", serie_id="r", target_rom=80, max_safe_angle=95))
    service = SampleIngestService(state, OutboxRepository())

    for _ in range(40):
        service.ingest(KIT, 30.0, None)  # angle stalled but proximal absent

    assert OutboxRepository().count_pending() == 0
