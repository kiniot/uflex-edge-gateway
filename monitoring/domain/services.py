"""Domain services for the Monitoring bounded context.

Domain services encapsulate business logic that does not naturally belong to
a single entity.  ``MovementRecordService`` is responsible for validating raw
sensor input and constructing a well-formed
:class:`~monitoring.domain.entities.MovementRecord` aggregate, enforcing the
invariants of the Monitoring bounded context.
"""
from datetime import datetime, timezone
from statistics import mean

from dateutil.parser import parse

from monitoring.domain.entities import MovementRecord


class MovementRecordService:
    """Domain service responsible for the creation of valid movement records.

    This service enforces the business invariants of the Monitoring bounded
    context:

    - the flexion ``angle`` must be a numeric value in the physically
      plausible range [0, 360] degrees.
    - ``created_at``, when supplied, must be a valid ISO 8601 timestamp;
      if omitted, the current UTC time is used.
    """

    @staticmethod
    def create_record(device_id: str, angle: float, created_at: str | None,
                      serie_id: str | None = None) -> MovementRecord:
        """Validate raw sensor data and create a new :class:`MovementRecord` entity.

        Applies the domain invariants before constructing the aggregate:

        * ``angle`` is coerced to ``float`` and validated in the range
          [0, 360] degrees.
        * ``created_at`` is parsed and converted to UTC; when ``None`` the
          current UTC timestamp is used.

        Args:
            device_id (str): Identifier of the originating kit.
            angle (float): Joint flexion angle reading in degrees.
            created_at (str | None): ISO 8601 timestamp of the reading
                (e.g. ``'2026-05-29T18:23:00-05:00'``), or ``None`` to
                default to the current UTC time.
            serie_id (str | None): Series this reading belongs to, stamped by
                the application service from the device's open series execution.

        Returns:
            MovementRecord: A new, unsaved :class:`MovementRecord` domain
            entity with a UTC-normalized ``created_at`` value.

        Raises:
            ValueError: If ``angle`` is not convertible to ``float``, falls
                outside [0, 360], or if ``created_at`` is not a valid ISO 8601
                string.
        """
        try:
            angle = float(angle)
            if not (0 <= angle <= 360):
                raise ValueError("Invalid angle value")
            if created_at:
                parsed_created_at = parse(created_at).astimezone(timezone.utc)
            else:
                parsed_created_at = datetime.now(timezone.utc)
        except (ValueError, TypeError):
            raise ValueError("Invalid data format")

        return MovementRecord(device_id, angle, parsed_created_at, serie_id=serie_id)


class MovementAnalysisService:
    """Domain service that derives clinical movement metrics from a series of
    raw flexion readings.

    This is where the edge gateway earns its "processing" role: instead of
    forwarding thousands of raw angle points, it chews them into a compact,
    clinically meaningful summary (range of motion, repetitions, speed) and
    evaluates them against the thresholds supplied by the backend to decide
    whether an actuator should fire.

    The service is **pure**: it operates only on the data it is given and has
    no knowledge of persistence, HTTP, or the actuator transport.

    Tuning constants:
        MIN_ROM_FOR_REP (float): Minimum overall range of motion (degrees) for
            the series to contain any real repetition rather than sensor jitter.
        REP_DETECTION_FRACTION (float): Fraction (0-1) of the target ROM a
            flexion must rise above its *local* extension baseline to count as a
            repetition attempt. Using a local baseline (not the global peak)
            makes detection robust to repetitions of differing amplitude.
    """

    MIN_ROM_FOR_REP = 10.0
    REP_DETECTION_FRACTION = 0.5

    @classmethod
    def analyze(cls, samples, target_rom=None, max_safe_angle=None):
        """Compute the digested movement summary for a chronological series of readings.

        Args:
            samples (list[MovementRecord]): Readings ordered oldest-to-newest.
            target_rom (float | None): Backend-defined range-of-motion goal in
                degrees.  When provided, the summary reports whether it was met.
            max_safe_angle (float | None): Backend-defined safety ceiling in
                degrees.  When provided, the summary reports whether it was
                exceeded and the resulting actuator action.

        Returns:
            dict: A summary with ``sample_count``, ``min_angle``, ``max_angle``,
            ``range_of_motion``, ``mean_angle``, ``repetitions``,
            ``peak_angular_velocity`` (deg/s), ``duration_seconds`` and
            ``threshold_evaluation``.  Numeric fields are ``None`` when there
            are no samples to derive them from.
        """
        angles = [s.angle for s in samples]
        summary = {
            "sample_count": len(angles),
            "min_angle": None,
            "max_angle": None,
            "range_of_motion": None,
            "mean_angle": None,
            "repetitions": 0,
            "peak_angular_velocity": None,
            "duration_seconds": None,
            "threshold_evaluation": None,
        }
        if not angles:
            return summary

        min_angle = min(angles)
        max_angle = max(angles)
        rom = max_angle - min_angle

        summary["min_angle"] = round(min_angle, 2)
        summary["max_angle"] = round(max_angle, 2)
        summary["range_of_motion"] = round(rom, 2)
        summary["mean_angle"] = round(mean(angles), 2)
        summary["repetitions"] = len(cls.evaluate_repetitions(samples, target_rom, max_safe_angle))
        summary["peak_angular_velocity"] = cls._peak_angular_velocity(samples)
        summary["duration_seconds"] = cls._duration_seconds(samples)
        summary["threshold_evaluation"] = cls._evaluate_threshold(
            rom, max_angle, target_rom, max_safe_angle
        )
        return summary

    @staticmethod
    def _peak_angular_velocity(samples):
        """Return the fastest instantaneous angular speed (deg/s) between
        consecutive readings, or ``None`` when no valid time delta exists."""
        peak = 0.0
        measured = False
        for previous, current in zip(samples, samples[1:]):
            delta_seconds = (current.created_at - previous.created_at).total_seconds()
            if delta_seconds > 0:
                measured = True
                velocity = abs(current.angle - previous.angle) / delta_seconds
                peak = max(peak, velocity)
        return round(peak, 2) if measured else None

    @staticmethod
    def _duration_seconds(samples):
        """Return the elapsed time (seconds) spanned by the readings."""
        if len(samples) < 2:
            return 0.0
        return round((samples[-1].created_at - samples[0].created_at).total_seconds(), 2)

    @staticmethod
    def _evaluate_threshold(rom, max_angle, target_rom, max_safe_angle):
        """Compare the derived metrics against backend-supplied thresholds.

        Produces the decision the actuator layer will act on: whether the
        rehabilitation goal was met and whether a safety ceiling was crossed.
        Returns ``None`` when no thresholds were supplied.
        """
        evaluation = {}
        if target_rom is not None:
            evaluation["target_rom"] = target_rom
            evaluation["rom_goal_met"] = rom >= target_rom
        if max_safe_angle is not None:
            exceeded = max_angle >= max_safe_angle
            evaluation["max_safe_angle"] = max_safe_angle
            evaluation["safe_limit_exceeded"] = exceeded
            # Decision consumed by the (future) actuator transport.
            evaluation["actuator_action"] = "ACTIVATE" if exceeded else "IDLE"
        return evaluation or None

    @classmethod
    def evaluate_repetitions(cls, samples, target_rom=None, max_safe_angle=None):
        """Segment the reading series into repetitions and classify each one.

        Walks the angle series with the same hysteresis state machine used for
        counting, but additionally captures, for every completed flex-and-return
        cycle, the achieved range of motion (peak minus the extension baseline
        it started from) and the peak angle.  Each repetition is then classified
        against the series target and the safety ceiling.

        Args:
            samples (list[MovementRecord]): Readings ordered oldest-to-newest.
            target_rom (float | None): Series target ROM in degrees; a repetition
                that does not reach it is "incomplete".
            max_safe_angle (float | None): Safety ceiling in degrees; a
                repetition whose peak reaches it is "unsafe".

        Returns:
            list[dict]: One entry per repetition, each with ``achieved_rom``,
            ``peak_angle``, ``met_target``, ``unsafe`` and ``classification``
            (``"good"`` | ``"incomplete"`` | ``"unsafe"``).
        """
        angles = [s.angle for s in samples]
        if len(angles) < 2 or (max(angles) - min(angles)) < cls.MIN_ROM_FOR_REP:
            return []

        # A flexion must rise at least this many degrees above its *local*
        # extension baseline to count as a repetition attempt. Derived from the
        # target so that incomplete reps are still detected (and flagged), with a
        # floor; falls back to MIN_ROM_FOR_REP when no target is supplied.
        if target_rom:
            excursion_threshold = max(cls.MIN_ROM_FOR_REP, cls.REP_DETECTION_FRACTION * target_rom)
        else:
            excursion_threshold = cls.MIN_ROM_FOR_REP

        repetitions = []
        state = "extension"
        baseline = angles[0]
        peak = angles[0]
        for angle in angles:
            if state == "extension":
                baseline = min(baseline, angle)
                if angle - baseline >= excursion_threshold:
                    state = "flexion"
                    peak = angle
            else:  # flexion
                peak = max(peak, angle)
                if peak - angle >= excursion_threshold:
                    repetitions.append(
                        cls._classify_repetition(peak - baseline, peak, target_rom, max_safe_angle)
                    )
                    state = "extension"
                    baseline = angle
        # A flexion still open at the end of the series (its return was cut off)
        # still counts if it cleared the detection threshold.
        if state == "flexion" and (peak - baseline) >= excursion_threshold:
            repetitions.append(
                cls._classify_repetition(peak - baseline, peak, target_rom, max_safe_angle)
            )
        return repetitions

    @staticmethod
    def _classify_repetition(achieved_rom, peak_angle, target_rom, max_safe_angle):
        """Label a single repetition as good, incomplete or unsafe.

        Safety takes precedence: a repetition that crosses the ceiling is
        ``"unsafe"`` regardless of its range.  Otherwise a repetition that does
        not reach the target ROM is ``"incomplete"``; one that does (or when no
        target was given) is ``"good"``.
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

    @classmethod
    def summarize_execution(cls, samples, target_rom=None, target_reps=None, max_safe_angle=None):
        """Produce the aggregated result of a series execution.

        Classifies each repetition and rolls the outcome up into the durable
        series summary: good/bad counts, average achieved ROM (the value the
        series reports), a quality ``valoracion`` (percentage of good reps) and a
        danger flag.

        Args:
            samples (list[MovementRecord]): Readings for the whole series.
            target_rom (float | None): Series target ROM in degrees.
            target_reps (int | None): Expected repetition count.
            max_safe_angle (float | None): Safety ceiling in degrees.

        Returns:
            dict: Aggregated outcome plus the per-repetition ``repetitions`` list.
        """
        repetitions = cls.evaluate_repetitions(samples, target_rom, max_safe_angle)
        angles = [s.angle for s in samples]
        good = sum(1 for r in repetitions if r["classification"] == "good")
        incomplete = sum(1 for r in repetitions if r["classification"] == "incomplete")
        unsafe = sum(1 for r in repetitions if r["classification"] == "unsafe")
        reps_done = len(repetitions)
        achieved_roms = [r["achieved_rom"] for r in repetitions]
        return {
            "reps_done": reps_done,
            "good_reps": good,
            "bad_reps_incomplete": incomplete,
            "bad_reps_unsafe": unsafe,
            "avg_rom": round(mean(achieved_roms), 2) if achieved_roms else None,
            "min_angle": round(min(angles), 2) if angles else None,
            "max_angle": round(max(angles), 2) if angles else None,
            "valoracion": round(100.0 * good / reps_done, 1) if reps_done else 0.0,
            "dangerous_movement_detected": unsafe > 0,
            "reps_target_met": target_reps is None or reps_done >= target_reps,
            "repetitions": repetitions,
        }
