"""Domain services for the Monitoring bounded context.

Domain services encapsulate business logic that does not naturally belong to
a single entity.  ``MovementRecordService`` is responsible for validating raw
sensor input and constructing a well-formed
:class:`~monitoring.domain.entities.MovementRecord` aggregate, enforcing the
invariants of the Monitoring bounded context.
"""
from datetime import datetime, timezone

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
    def create_record(device_id: str, angle: float, created_at: str | None) -> MovementRecord:
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

        return MovementRecord(device_id, angle, parsed_created_at)
