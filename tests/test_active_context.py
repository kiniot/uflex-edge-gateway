"""Unit tests for the active-context down-channel: movement normalization + payload shape.

The firmware needs the movement (not just the joint) to pick the IMU pair for pron/sup, so
active_context must carry a normalized active_movement.
"""
from app.detection.application.services import DebugViewService
from app.detection.application.state import EdgeRuntimeState
from app.detection.domain.entities import ExecutionContext
from app.detection.domain.services import normalize_movement

KIT = "uflex-kit-001"


def test_normalize_movement_maps_known_values_case_insensitively():
    assert normalize_movement("FLEXION") == "FLEXION"
    assert normalize_movement("pronation") == "PRONATION"
    assert normalize_movement("Supination") == "SUPINATION"
    assert normalize_movement("extension") == "EXTENSION"


def test_normalize_movement_none_or_unknown():
    assert normalize_movement(None) is None
    assert normalize_movement("") is None
    assert normalize_movement("TWIST") is None  # unmapped -> None (logged), not a wrong pair


def test_active_context_includes_normalized_joint_and_movement():
    state = EdgeRuntimeState()
    state.update_context(KIT, ExecutionContext(
        session_id="sess-1", serie_id="ser-1", target_rom=80, max_safe_angle=95,
        body_part="WRIST", movement_type="PRONATION"))

    payload = DebugViewService(state).active_context(KIT)

    assert payload["active_joint"] == "WRIST"
    assert payload["active_movement"] == "PRONATION"
    assert payload["serie_id"] == "ser-1"
