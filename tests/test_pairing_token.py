"""Tests for the SSE pairing-token auth: pure validator, in-memory token state, and the
correlation poller caching the token from the active-by-device response (and clearing it on 404)."""
from app.detection.application.correlation import CorrelationPoller
from app.detection.application.state import EdgeRuntimeState
from app.detection.interfaces.services import is_pairing_token_valid
from app.shared.infrastructure.network import get_lan_ipv4

KIT = "uflex-kit-001"


# --- pure validator -------------------------------------------------------

def test_token_validator_accepts_only_exact_match():
    assert is_pairing_token_valid("tok-abc", "tok-abc") is True


def test_token_validator_rejects_mismatch_and_missing():
    assert is_pairing_token_valid("tok-abc", "tok-xyz") is False
    assert is_pairing_token_valid(None, "tok-abc") is False   # no active session for the kit
    assert is_pairing_token_valid("tok-abc", None) is False   # client sent nothing
    assert is_pairing_token_valid(None, None) is False
    assert is_pairing_token_valid("", "") is False


# --- in-memory token state ------------------------------------------------

def test_state_pairing_token_set_get_clear():
    state = EdgeRuntimeState()
    assert state.get_pairing_token(KIT) is None
    state.set_pairing_token(KIT, "tok-1")
    assert state.get_pairing_token(KIT) == "tok-1"
    state.set_pairing_token(KIT, None)
    assert state.get_pairing_token(KIT) is None


# --- poller token caching -------------------------------------------------

class _FakeResp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self.ok = status_code < 400
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeClient:
    """Minimal stand-in for BackendClient: pops queued GET responses; PUT is a no-op 204."""

    def __init__(self, get_responses):
        self._get_responses = list(get_responses)
        self.calls = []

    def get(self, path):
        self.calls.append(("GET", path))
        return self._get_responses.pop(0)

    def put(self, path, json=None):
        self.calls.append(("PUT", path, json))
        return _FakeResp(204)


def _poller_with(get_responses):
    return CorrelationPoller(KIT, _FakeClient(get_responses), EdgeRuntimeState(),
                             interval_seconds=1.0, lan_url="http://192.168.1.4:5050")


def test_poller_caches_token_from_active_session():
    payload = {
        "id": "sess-1",
        "edgePairingToken": "tok-xyz",
        "series": [{"serieId": "ser-1", "status": "Started", "targetRom": 80, "targetRepetitions": 4}],
    }
    poller = _poller_with([_FakeResp(200, payload)])
    poller._poll_once()
    assert poller._state.get_pairing_token(KIT) == "tok-xyz"


def test_poller_clears_token_when_no_active_session():
    poller = _poller_with([_FakeResp(404)])
    poller._state.set_pairing_token(KIT, "stale")
    poller._poll_once()
    assert poller._state.get_pairing_token(KIT) is None


# --- LAN IP helper --------------------------------------------------------

def test_get_lan_ipv4_returns_dotted_quad():
    ip = get_lan_ipv4()
    parts = ip.split(".")
    assert len(parts) == 4 and all(p.isdigit() for p in parts)
