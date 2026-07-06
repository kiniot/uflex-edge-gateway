"""Forwarding worker: drains the outbox to the backend, in order, with retries.

Reads PENDING outbox entries in FIFO order and forwards each via the
:class:`BackendForwarder`. A transient failure stops the pass (preserving order) and retries next
cycle; a permanent rejection quarantines the entry and keeps draining, so one poison entry cannot
block the queue behind it — resilient to transient outages without losing or reordering the rest.
"""
import logging
import threading

from app.detection.infrastructure.backend_forwarder import ForwardOutcome

logger = logging.getLogger(__name__)


class ForwardingWorker(threading.Thread):
    """Background thread that flushes the durable outbox to the backend."""

    def __init__(self, outbox_repo, forwarder, interval_seconds: float = 1.0, batch_size: int = 50):
        super().__init__(daemon=True, name="edge-forwarding")
        self._outbox = outbox_repo
        self._forwarder = forwarder
        self._interval = interval_seconds
        self._batch_size = batch_size
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        logger.info("Forwarding worker started")
        while not self._stop.is_set():
            try:
                self._drain_once()
            except Exception as exc:  # noqa: BLE001 — keep the worker alive through errors
                logger.warning("Outbox drain failed: %s", exc)
            self._stop.wait(self._interval)

    def _drain_once(self) -> None:
        for entry in self._outbox.find_pending(self._batch_size):
            outcome = self._forwarder.forward(entry)
            if outcome is ForwardOutcome.SENT:
                self._outbox.mark_sent(entry.id)
            elif outcome is ForwardOutcome.DROP:
                # Permanent rejection: quarantine and keep draining so it can't block the queue.
                self._outbox.mark_failed(entry.id)
            else:
                # Transient (RETRY): preserve FIFO order, stop the pass, retry next cycle.
                break
