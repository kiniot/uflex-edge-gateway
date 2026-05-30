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
