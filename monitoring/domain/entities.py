"""Domain entities for the Monitoring bounded context.

This module defines the core aggregate of the Monitoring bounded context.
Entities carry identity and encapsulate domain state; they should only be
created or mutated through domain services that enforce business invariants.
"""
from datetime import datetime


class MovementRecord:
    """Aggregate root representing a single range-of-motion reading.

    A ``MovementRecord`` captures a joint flexion angle measured by a specific
    uFlex IoT Kit at a given point in time during a rehabilitation exercise.
    Instances are created by
    :meth:`~monitoring.domain.services.MovementRecordService.create_record`,
    which validates the raw sensor data before constructing this entity.

    Attributes:
        id (int | None): Surrogate identity assigned by the persistence layer
            after the record is saved.  ``None`` for transient (unsaved)
            instances.
        device_id (str): Identifier of the kit that produced the reading.
        angle (float): Joint flexion angle measured in degrees.
        created_at (datetime): UTC timestamp of when the reading was taken.
    """

    def __init__(self, device_id: str, angle: float, created_at: datetime, id: int = None):
        """Initialise a MovementRecord entity.

        Args:
            device_id (str): Identifier of the originating kit.
            angle (float): Joint flexion angle in degrees.
            created_at (datetime): UTC timestamp of the reading.
            id (int, optional): Persistence identity.  Defaults to ``None``
                for transient entities that have not been saved yet.
        """
        self.id = id
        self.device_id = device_id
        self.angle = angle
        self.created_at = created_at


class SerieExecution:
    """Aggregate representing the execution of one therapy *series*.

    A series is the unit of exercise a patient performs (an exercise plus its
    target parameters).  This aggregate captures what actually happened when the
    series was executed: how many repetitions were done, how many were good or
    bad, the average achieved range of motion and a quality ``valoracion``.

    The *definition* of the series (and of its parent routine/plan) lives in the
    backend; this aggregate is the *execution* result the edge produces and
    forwards.  See ``docs/edge-execution-design.md``.

    Lifecycle: created with ``status='OPEN'`` by ``series/start``; populated with
    the computed results and moved to ``status='CLOSED'`` by ``series/end``.

    Attributes:
        id (int | None): Persistence identity, ``None`` until saved.
        serie_id (str | None): Reference to the series definition in the backend.
        device_id (str): Kit that produced the readings.
        target_rom (float | None): Target range of motion for the series (deg).
        target_reps (int | None): Expected number of repetitions.
        movement_type (str | None): pronation / supination / flexion / extension.
        body_part (str | None): elbow / wrist.
        max_safe_angle (float | None): Safety ceiling (deg).
        started_at (datetime): When the series execution began (UTC).
        ended_at (datetime | None): When it was closed (UTC); ``None`` while open.
        status (str): ``OPEN`` | ``CLOSED`` | ``DISCARDED``.
        reps_done (int): Repetitions detected.
        good_reps (int): Repetitions that met the target and stayed safe.
        bad_reps_incomplete (int): Repetitions that fell short of the target ROM.
        bad_reps_unsafe (int): Repetitions that crossed the safety ceiling.
        avg_rom (float | None): Average achieved ROM across repetitions.
        min_angle (float | None): Lowest angle observed.
        max_angle (float | None): Highest angle observed.
        valoracion (float | None): Quality score, percentage of good repetitions.
        dangerous_movement_detected (bool): Whether any unsafe movement occurred.
    """

    def __init__(self, serie_id, device_id, started_at,
                 target_rom=None, target_reps=None, movement_type=None,
                 body_part=None, max_safe_angle=None, ended_at=None,
                 status="OPEN", reps_done=0, good_reps=0,
                 bad_reps_incomplete=0, bad_reps_unsafe=0, avg_rom=None,
                 min_angle=None, max_angle=None, valoracion=None,
                 dangerous_movement_detected=False, id=None):
        """Initialise a SerieExecution aggregate (see class docstring for fields)."""
        self.id = id
        self.serie_id = serie_id
        self.device_id = device_id
        self.target_rom = target_rom
        self.target_reps = target_reps
        self.movement_type = movement_type
        self.body_part = body_part
        self.max_safe_angle = max_safe_angle
        self.started_at = started_at
        self.ended_at = ended_at
        self.status = status
        self.reps_done = reps_done
        self.good_reps = good_reps
        self.bad_reps_incomplete = bad_reps_incomplete
        self.bad_reps_unsafe = bad_reps_unsafe
        self.avg_rom = avg_rom
        self.min_angle = min_angle
        self.max_angle = max_angle
        self.valoracion = valoracion
        self.dangerous_movement_detected = dangerous_movement_detected
