"""Correlation poller: discovers the kit's active serie from the backend.

There is no mobile→edge channel yet (§13.0.b), so the edge learns which serie is
active by polling the backend's authoritative read endpoint
``GET /active/by-device/{serial}`` and picking the serie in ``Started`` status. It
hydrates an :class:`ExecutionContext` (targets) into the in-memory state; the
detector is (re)installed by the state on a serie change. Self-healing: a missed
poll just resolves on the next tick.
"""
import logging
import threading

from monitoring.domain.entities import ExecutionContext
from monitoring.domain.services import derive_max_safe_angle

logger = logging.getLogger(__name__)


class CorrelationPoller(threading.Thread):
    """Background thread polling ``active/by-device`` to keep the active context fresh."""

    def __init__(self, serial_number: str, backend_client, state, interval_seconds: float = 3.0):
        super().__init__(daemon=True, name=f"edge-correlation-{serial_number}")
        self._serial = serial_number
        self._client = backend_client
        self._state = state
        self._interval = interval_seconds
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        logger.info("Correlation poller started for %s", self._serial)
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception as exc:  # noqa: BLE001 — keep polling through transient errors
                logger.warning("active-by-device poll failed for %s: %s", self._serial, exc)
            self._stop.wait(self._interval)

    def _poll_once(self) -> None:
        response = self._client.get(f"/api/v1/therapy-sessions/active/by-device/{self._serial}")
        if response.status_code == 200:
            self._state.update_context(self._serial, self._to_context(response.json()))
        elif response.status_code == 404:
            # No active session for this kit -> clear context (samples are buffered/ignored).
            self._state.update_context(self._serial, None)
        else:
            logger.debug("active-by-device -> HTTP %s; keeping current context", response.status_code)

    @staticmethod
    def _to_context(data: dict):
        """Build an ExecutionContext from the active session, or ``None`` if no serie is Started."""
        series = data.get("series") or []
        started = next((s for s in series if s.get("status") == "Started"), None)
        if not started:
            return None
        target_rom = started.get("targetRom")
        return ExecutionContext(
            session_id=str(data.get("id")),
            serie_id=str(started.get("serieId")),
            target_rom=target_rom,
            target_reps=started.get("targetRepetitions"),
            movement_type=started.get("movementType"),
            body_part=started.get("bodyPart"),
            max_safe_angle=derive_max_safe_angle(target_rom),
        )
