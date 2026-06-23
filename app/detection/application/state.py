"""In-memory runtime state of the edge, shared across threads.

The edge is now stateful: per kit it holds the active :class:`ExecutionContext`,
the streaming :class:`IncrementalRepetitionDetector`, and a transient window of
recent samples (the raw buffer is no longer durable). Access is guarded by a lock
because the Flask request thread (ingest) and the correlation poller touch this
state concurrently. Safe and simple given 1 edge ↔ 1 kit.
"""
import threading
from collections import deque
from typing import Optional

from app.detection.domain.entities import ExecutionContext, MovementSample
from app.detection.domain.services import IncrementalRepetitionDetector

_WINDOW_SIZE = 500


class _KitState:
    def __init__(self):
        self.context: Optional[ExecutionContext] = None
        self.detector: Optional[IncrementalRepetitionDetector] = None
        self.window: deque = deque(maxlen=_WINDOW_SIZE)
        self.reps_detected: int = 0  # edge-local running tally for the active serie


class EdgeRuntimeState:
    """Thread-safe holder of per-kit execution context, detector and sample window."""

    def __init__(self):
        self._kits: dict[str, _KitState] = {}
        self._lock = threading.RLock()

    def _kit(self, serial: str) -> _KitState:
        st = self._kits.get(serial)
        if st is None:
            st = _KitState()
            self._kits[serial] = st
        return st

    def update_context(self, serial: str, new_context: Optional[ExecutionContext]) -> bool:
        """Install the active serie for a kit. Returns ``True`` when it changed.

        On a serie change (or clear), a fresh detector is installed; any open
        half-repetition at the boundary is dropped (boundaries are driven by the
        backend, which already recorded the completed reps).
        """
        with self._lock:
            st = self._kit(serial)
            old = st.context
            same = (old is not None and new_context is not None
                    and old.session_id == new_context.session_id
                    and old.serie_id == new_context.serie_id)
            if same:
                return False
            st.context = new_context
            st.detector = (IncrementalRepetitionDetector(new_context.target_rom, new_context.max_safe_angle)
                           if new_context is not None else None)
            st.reps_detected = 0  # new serie (or clear) -> reset the live tally
            return True

    def ingest_sample(self, serial: str, sample: MovementSample):
        """Buffer a sample and feed the detector.

        Returns ``(rep_dict, context, reps_detected)`` when the sample closes a
        repetition, else ``(None, None, reps_detected)``. ``reps_detected`` is the
        edge-local running tally for the active serie (resets on serie change).
        """
        with self._lock:
            st = self._kit(serial)
            st.window.append(sample)
            if st.context is None or st.detector is None:
                return None, None, st.reps_detected
            rep = st.detector.add_sample(sample.angle)
            if rep:
                st.reps_detected += 1
                return rep, st.context, st.reps_detected
            return None, None, st.reps_detected

    def context(self, serial: str) -> Optional[ExecutionContext]:
        with self._lock:
            st = self._kits.get(serial)
            return st.context if st else None

    def window(self, serial: str) -> list:
        with self._lock:
            st = self._kits.get(serial)
            return list(st.window) if st else []
