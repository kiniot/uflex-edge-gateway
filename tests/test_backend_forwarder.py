"""Unit tests for BackendForwarder.forward() outcome classification.

A permanent 4xx must DROP (quarantine) so it never blocks the FIFO queue; transient failures
(5xx, network errors, recoverable 4xx) must RETRY; a 2xx must be SENT.
"""
from app.detection.infrastructure.backend_forwarder import BackendForwarder, ForwardOutcome
from app.detection.infrastructure.repositories import OutboxEntry


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300


class _FakeClient:
    """Returns a canned status, or raises to simulate a network error."""

    def __init__(self, status_code=None, raises=False):
        self._status_code = status_code
        self._raises = raises

    def post(self, path, json=None, headers=None):
        if self._raises:
            raise ConnectionError("boom")
        return _FakeResponse(self._status_code)


def _entry(kind="repetition"):
    return OutboxEntry(
        id=1, kind=kind, serial_number="kit", session_id="sess", serie_id="ser",
        edge_sequence_id="uuid", payload={"peakAngle": 90.0}, forward_status="PENDING",
    )


def test_2xx_is_sent():
    forwarder = BackendForwarder(_FakeClient(status_code=201))
    assert forwarder.forward(_entry()) is ForwardOutcome.SENT


def test_permanent_4xx_is_dropped():
    # 400 (bad body) and 404 (gone/cancelled session) are permanent -> quarantine, don't retry.
    assert BackendForwarder(_FakeClient(status_code=400)).forward(_entry()) is ForwardOutcome.DROP
    assert BackendForwarder(_FakeClient(status_code=404)).forward(_entry()) is ForwardOutcome.DROP
    assert BackendForwarder(_FakeClient(status_code=409)).forward(_entry()) is ForwardOutcome.DROP


def test_transient_failures_retry():
    assert BackendForwarder(_FakeClient(status_code=500)).forward(_entry()) is ForwardOutcome.RETRY
    assert BackendForwarder(_FakeClient(status_code=401)).forward(_entry()) is ForwardOutcome.RETRY
    assert BackendForwarder(_FakeClient(status_code=503)).forward(_entry()) is ForwardOutcome.RETRY
    assert BackendForwarder(_FakeClient(raises=True)).forward(_entry()) is ForwardOutcome.RETRY


def test_unknown_kind_is_dropped():
    assert BackendForwarder(_FakeClient(status_code=201)).forward(_entry(kind="mystery")) is ForwardOutcome.DROP
