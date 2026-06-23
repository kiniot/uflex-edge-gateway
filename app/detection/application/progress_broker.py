"""In-process pub/sub for live progress events (the SSE fan-out).

The ingest thread publishes a small event each time a repetition is detected; each
SSE request thread subscribes with its own bounded queue and streams what arrives.
A slow or dead subscriber never blocks ingest: a full queue drops the event for that
subscriber (the next event's absolute tally re-asserts the truth, and the backend
poll reconciles regardless).
"""
import queue
import threading
from typing import Dict, Set

_QUEUE_MAXSIZE = 100


class ProgressBroker:
    """Thread-safe per-kit fan-out of live progress events to SSE subscribers."""

    def __init__(self):
        self._subscribers: Dict[str, Set[queue.Queue]] = {}
        self._lock = threading.Lock()

    def subscribe(self, serial_number: str) -> queue.Queue:
        """Register a new subscriber for a kit; returns its bounded event queue."""
        q: queue.Queue = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        with self._lock:
            self._subscribers.setdefault(serial_number, set()).add(q)
        return q

    def unsubscribe(self, serial_number: str, q: queue.Queue) -> None:
        """Remove a subscriber (called on client disconnect)."""
        with self._lock:
            subs = self._subscribers.get(serial_number)
            if subs is not None:
                subs.discard(q)
                if not subs:
                    del self._subscribers[serial_number]

    def publish(self, serial_number: str, event: dict) -> None:
        """Fan an event out to a kit's subscribers; never blocks, never raises.

        A subscriber whose queue is full is skipped (its next event re-asserts the
        absolute count), so a slow consumer can never stall the ingest thread.
        """
        with self._lock:
            subs = list(self._subscribers.get(serial_number, ()))
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass
