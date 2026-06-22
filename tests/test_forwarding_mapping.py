"""Unit tests for the edge -> backend payload mapping."""
from datetime import datetime

from monitoring.domain.entities import DetectedRepetition
from monitoring.infrastructure.backend_forwarder import repetition_payload


def _rep(classification="good"):
    return DetectedRepetition(
        serial_number="kit",
        session_id="sess",
        serie_id="ser",
        edge_sequence_id="uuid",
        achieved_rom=87.5,
        peak_angle=90.0,
        classification=classification,
        met_target=True,
        unsafe=False,
        recorded_at=datetime(2026, 6, 22, 5, 13, 50, 764911),
    )


def test_classification_is_pascal_case_and_fields_map():
    payload = repetition_payload(_rep("good"))
    assert payload["classification"] == "Good"
    assert payload["peakAngle"] == 90.0
    assert payload["achievedRom"] == 87.5


def test_recorded_at_uses_backend_millisecond_format():
    payload = repetition_payload(_rep())
    assert payload["recordedAt"] == "2026-06-22 05:13:50.764"


def test_incomplete_and_unsafe_map_to_pascal_case():
    assert repetition_payload(_rep("incomplete"))["classification"] == "Incomplete"
    assert repetition_payload(_rep("unsafe"))["classification"] == "Unsafe"
