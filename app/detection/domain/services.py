"""Domain services for the Detection bounded context.

Holds the edge's detection logic: validating raw samples and the **incremental**
repetition detector — a hysteresis state machine that consumes one angle at a
time and emits a repetition as soon as a flex-and-return cycle completes (rather
than analysing a whole buffer in batch).
"""
import logging
from collections import deque
from datetime import datetime, timezone
from statistics import mean
from typing import Optional

from dateutil.parser import parse

from app.detection.domain.entities import MovementSample

# Tuning constants (carried over from the original batch analysis).
MIN_ROM_FOR_REP = 10.0
REP_DETECTION_FRACTION = 0.5
# Margin added to the target ROM to derive the absolute safety ceiling. The
# backend does not store maxSafeAngle (the edge derives it); revisit clinically.
SAFE_MARGIN_DEGREES = 15.0

# Compensation detection (Wave 2). Tunables expressed in SAMPLES (the detector sees
# the edge publish cadence, ~10 Hz today -> a 20-sample window ~= 2 s); refine on
# hardware once the magnetometer-anchored proximal yaw is real.
COMPENSATION_WINDOW_SIZE = 20
COMPENSATION_PROXIMAL_RANGE_DEG = 15.0
COMPENSATION_ANGLE_STALL_DEG = 10.0
COMPENSATION_COOLDOWN_SAMPLES = 20
# A single proximal IMU (upper arm) cannot separate shoulder hike from trunk lean,
# so every detection is reported as shoulder compensation for now.
COMPENSATION_TYPE = "ShoulderCompensation"

logger = logging.getLogger(__name__)

# Maps a backend body-part value to the firmware's joint enum. The backend emits
# the BodyPart enum name (ELBOW/WRIST); lowercase and a couple of Spanish terms
# are tolerated defensively so an unmapped value is visible, not silent.
_JOINT_ALIASES = {
    "elbow": "ELBOW", "codo": "ELBOW",
    "wrist": "WRIST", "muneca": "WRIST", "muñeca": "WRIST",
}


def normalize_joint(body_part: Optional[str]) -> Optional[str]:
    """Normalize a backend body-part string to the firmware joint enum.

    Returns ``"ELBOW"`` | ``"WRIST"`` | ``None`` (case-insensitive). An unmapped,
    non-empty value is logged at WARNING and returns ``None`` so the firmware
    falls back to no active joint rather than a wrong one.
    """
    if not body_part:
        return None
    joint = _JOINT_ALIASES.get(body_part.strip().lower())
    if joint is None:
        logger.warning("Unmapped body_part '%s' (no joint normalization)", body_part)
    return joint


# The backend movementType enum names, tolerated case-insensitively. The firmware needs the movement
# (not just the joint) to pick the IMU pair: pronation/supination is forearm axial rotation, so the
# hand moves with the forearm and it must be measured against the upper arm (upper-middle), not the
# hand (middle-lower).
_MOVEMENT_NAMES = {"flexion": "FLEXION", "extension": "EXTENSION",
                   "pronation": "PRONATION", "supination": "SUPINATION"}


def normalize_movement(movement_type: Optional[str]) -> Optional[str]:
    """Normalize a backend movement-type string to the firmware movement enum name.

    Returns ``"FLEXION"`` | ``"EXTENSION"`` | ``"PRONATION"`` | ``"SUPINATION"`` | ``None``
    (case-insensitive). An unmapped, non-empty value is logged at WARNING and returns ``None`` so the
    firmware falls back to joint-only pair selection rather than a wrong pair.
    """
    if not movement_type:
        return None
    movement = _MOVEMENT_NAMES.get(movement_type.strip().lower())
    if movement is None:
        logger.warning("Unmapped movement_type '%s' (no movement normalization)", movement_type)
    return movement


def _coerce_optional_float(value) -> Optional[float]:
    """Best-effort float coercion that never raises (returns ``None`` on failure)."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def build_sample(serial_number: str, angle, created_at: Optional[str],
                 proximal=None) -> MovementSample:
    """Validate raw sensor input and build a :class:`MovementSample`.

    Args:
        serial_number: Originating kit serial.
        angle: Joint flexion angle; coerced to float, validated in [0, 360].
        created_at: ISO 8601 timestamp; UTC-normalized, or current UTC if ``None``.
        proximal: Optional proximal-segment signal (degrees). Coerced leniently to
            float, or dropped to ``None`` on a bad value — it is Wave-2 telemetry,
            so it never rejects an otherwise-valid sample.

    Raises:
        ValueError: On a non-numeric/out-of-range angle or a malformed timestamp.
    """
    try:
        angle = float(angle)
        if not (0 <= angle <= 360):
            raise ValueError("Invalid angle value")
        recorded_at = parse(created_at).astimezone(timezone.utc) if created_at else datetime.now(timezone.utc)
    except (ValueError, TypeError):
        raise ValueError("Invalid data format")
    return MovementSample(serial_number=serial_number, angle=angle, recorded_at=recorded_at,
                          proximal_signal=_coerce_optional_float(proximal))


def derive_max_safe_angle(target_rom: Optional[float]) -> Optional[float]:
    """Derive the absolute safety ceiling as ``target_rom + SAFE_MARGIN_DEGREES``.

    Returns ``None`` when no target ROM is known.
    """
    return target_rom + SAFE_MARGIN_DEGREES if target_rom else None


def classify_repetition(achieved_rom: float, peak_angle: float,
                        target_rom: Optional[float], max_safe_angle: Optional[float]) -> dict:
    """Label a single repetition as good, incomplete or unsafe.

    Safety takes precedence: a repetition whose peak crosses the ceiling is
    ``"unsafe"`` regardless of its range. Otherwise a repetition that does not
    reach the target ROM is ``"incomplete"``; one that does (or when no target
    was given) is ``"good"``.
    """
    unsafe = max_safe_angle is not None and peak_angle >= max_safe_angle
    met_target = target_rom is None or achieved_rom >= target_rom
    if unsafe:
        classification = "unsafe"
    elif not met_target:
        classification = "incomplete"
    else:
        classification = "good"
    return {
        "achieved_rom": round(achieved_rom, 2),
        "peak_angle": round(peak_angle, 2),
        "met_target": met_target,
        "unsafe": unsafe,
        "classification": classification,
    }


class IncrementalRepetitionDetector:
    """Streaming hysteresis detector: feed one angle at a time, get reps as they close.

    Mirrors the original batch state machine but keeps its state
    (``state``/``baseline``/``peak``) across calls. A flexion must rise at least
    ``excursion_threshold`` degrees above its *local* extension baseline to count,
    making detection robust to repetitions of differing amplitude.
    """

    def __init__(self, target_rom: Optional[float] = None, max_safe_angle: Optional[float] = None):
        self.target_rom = target_rom
        self.max_safe_angle = max_safe_angle
        if target_rom:
            self.excursion_threshold = max(MIN_ROM_FOR_REP, REP_DETECTION_FRACTION * target_rom)
        else:
            self.excursion_threshold = MIN_ROM_FOR_REP
        self._state = "extension"
        self._baseline: Optional[float] = None
        self._peak: Optional[float] = None

    def add_sample(self, angle: float) -> Optional[dict]:
        """Feed one angle; return a classified repetition dict when one completes, else ``None``."""
        if self._baseline is None:
            self._baseline = angle
            self._peak = angle
        if self._state == "extension":
            self._baseline = min(self._baseline, angle)
            if angle - self._baseline >= self.excursion_threshold:
                self._state = "flexion"
                self._peak = angle
            return None
        # flexion
        self._peak = max(self._peak, angle)
        if self._peak - angle >= self.excursion_threshold:
            rep = classify_repetition(self._peak - self._baseline, self._peak,
                                      self.target_rom, self.max_safe_angle)
            self._state = "extension"
            self._baseline = angle
            return rep
        return None

    def flush(self) -> Optional[dict]:
        """Emit a still-open flexion (its return was cut off) if it cleared the threshold.

        Call when the serie ends/changes. Returns the repetition or ``None``.
        """
        if (self._state == "flexion" and self._baseline is not None
                and (self._peak - self._baseline) >= self.excursion_threshold):
            rep = classify_repetition(self._peak - self._baseline, self._peak,
                                      self.target_rom, self.max_safe_angle)
            self._state = "extension"
            self._baseline = self._peak
            return rep
        return None


class CompensationDetector:
    """Streaming compensation detector: proximal segment moves while the target joint stalls.

    Per-serie instance (reinstalled on serie change, like the repetition detector).
    Keeps a short sliding window of ``(angle, proximal)`` pairs and fires when the
    proximal yaw sweeps more than ``proximal_range_threshold`` degrees while the
    target angle stays within ``angle_stall_threshold`` (the joint is not moving). A
    cooldown then suppresses further detections so one compensation *episode* yields a
    single event. No-ops when proximal data is absent (firmware not enriching, or a
    drifting-yaw guard), so a missing signal can never produce a false positive.
    """

    def __init__(self, proximal_range_threshold: float = COMPENSATION_PROXIMAL_RANGE_DEG,
                 angle_stall_threshold: float = COMPENSATION_ANGLE_STALL_DEG,
                 window_size: int = COMPENSATION_WINDOW_SIZE,
                 cooldown_samples: int = COMPENSATION_COOLDOWN_SAMPLES):
        self.proximal_range_threshold = proximal_range_threshold
        self.angle_stall_threshold = angle_stall_threshold
        self.cooldown_samples = cooldown_samples
        self._window: deque = deque(maxlen=window_size)
        self._cooldown_remaining = 0

    def add_sample(self, angle: float, proximal: Optional[float]) -> Optional[dict]:
        """Feed one ``(angle, proximal)`` pair; return a compensation dict when one fires, else ``None``."""
        if proximal is None:
            return None  # only proximal-bearing samples slide the window / decay the cooldown
        self._window.append((angle, proximal))
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
            return None
        if len(self._window) < self._window.maxlen:
            return None  # require a full window before judging a sustained episode
        angles = [a for a, _ in self._window]
        proximals = [p for _, p in self._window]
        proximal_range = max(proximals) - min(proximals)
        angle_range = max(angles) - min(angles)
        if proximal_range >= self.proximal_range_threshold and angle_range <= self.angle_stall_threshold:
            self._cooldown_remaining = self.cooldown_samples
            return {
                "type": COMPENSATION_TYPE,
                "proximal_range": round(proximal_range, 2),
                "angle_range": round(angle_range, 2),
            }
        return None


def window_summary(samples: list[MovementSample]) -> dict:
    """Lightweight live-view summary over the in-memory sample window (debug only)."""
    angles = [s.angle for s in samples]
    if not angles:
        return {"sample_count": 0, "min_angle": None, "max_angle": None,
                "range_of_motion": None, "mean_angle": None}
    lo, hi = min(angles), max(angles)
    return {
        "sample_count": len(angles),
        "min_angle": round(lo, 2),
        "max_angle": round(hi, 2),
        "range_of_motion": round(hi - lo, 2),
        "mean_angle": round(mean(angles), 2),
    }
