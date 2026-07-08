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

from app.detection.domain.entities import ExecutionContext
from app.detection.domain.services import derive_max_safe_angle

logger = logging.getLogger(__name__)


class CorrelationPoller(threading.Thread):
    """Background thread polling ``active/by-device`` to keep the active context fresh."""

    def __init__(self, serial_number: str, backend_client, state, interval_seconds: float = 3.0,
                 lan_url: str = None):
        super().__init__(daemon=True, name=f"edge-correlation-{serial_number}")
        self._serial = serial_number
        self._client = backend_client
        self._state = state
        self._interval = interval_seconds
        self._lan_url = lan_url
        self._cycles = 0
        # Re-report the LAN URL roughly every 60s (idempotent) so a backend restart relearns it,
        # without writing it on every 3s poll.
        self._report_every = max(1, int(60 / interval_seconds)) if interval_seconds else 1
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        logger.info("Correlation poller started for %s", self._serial)
        while not self._stop.is_set():
            if self._lan_url and self._cycles % self._report_every == 0:
                try:
                    self._report_lan_url()
                except Exception as exc:  # noqa: BLE001 — a failed report must not stop polling
                    logger.warning("lan-url report failed for %s: %s", self._serial, exc)
            try:
                self._poll_once()
            except Exception as exc:  # noqa: BLE001 — keep polling through transient errors
                logger.warning("active-by-device poll failed for %s: %s", self._serial, exc)
            self._cycles += 1
            self._stop.wait(self._interval)

    def _report_lan_url(self) -> None:
        """Report this edge's LAN URL to the backend for mobile rendezvous (idempotent PUT)."""
        response = self._client.put(
            "/api/v1/iam/edge-service-accounts/me/lan-url", json={"lanUrl": self._lan_url})
        if not getattr(response, "ok", response.status_code < 400):
            logger.debug("lan-url report -> HTTP %s", response.status_code)

    def _poll_once(self) -> None:
        response = self._client.get(f"/api/v1/therapy-sessions/active/by-device/{self._serial}")
        if response.status_code == 200:
            data = response.json()
            context = self._to_context(data)
            changed = self._state.update_context(self._serial, context)
            # The pairing token rides on the active-session payload; cache it for SSE auth.
            self._state.set_pairing_token(self._serial, data.get("edgePairingToken"))
            # Log once per serie change (not every 3s poll). A missing targetRom is the reason every
            # rep would classify as "good", so surface it loudly instead of silently defaulting.
            if changed and context is not None:
                if context.target_rom is None:
                    logger.warning(
                        "active serie %s has NO targetRom -> every rep will classify as 'good'; "
                        "check the plan's rangeOfMotion / backend serie.targetRom",
                        context.serie_id)
                else:
                    logger.info(
                        "active context: serie=%s bodyPart=%s targetRom=%.1f targetReps=%s "
                        "maxSafe=%.1f", context.serie_id, context.body_part, context.target_rom,
                        context.target_reps, context.max_safe_angle)
        elif response.status_code == 404:
            # No active session for this kit -> clear context + token (samples buffered/ignored).
            self._state.update_context(self._serial, None)
            self._state.set_pairing_token(self._serial, None)
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
