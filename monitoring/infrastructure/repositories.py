"""Repository implementation for the Monitoring bounded context.

Provides the persistence adapter that maps between the
:class:`~monitoring.domain.entities.MovementRecord` domain entity and the
:class:`~monitoring.infrastructure.models.MovementRecord` Peewee ORM model.

Following the Repository pattern, callers in the application layer interact
only with domain entities and are shielded from ORM/database details.
"""
from monitoring.domain.entities import MovementRecord
from monitoring.infrastructure.models import MovementRecord as MovementRecordModel


class MovementRecordRepository:
    """Repository that persists and reconstructs :class:`~monitoring.domain.entities.MovementRecord` entities.

    Acts as an in-process collection of domain entities backed by the SQLite
    database.  The mapping between the ORM model and the domain entity is
    handled entirely within this class, keeping the domain layer free of
    infrastructure concerns.
    """

    @staticmethod
    def save(movement_record: MovementRecord) -> MovementRecord:
        """Persist a transient :class:`~monitoring.domain.entities.MovementRecord` entity.

        Inserts a new row into the ``movement_records`` table using Peewee's
        ``create`` helper and returns a new domain entity instance populated
        with the database-assigned ``id``.

        Args:
            movement_record (MovementRecord): The transient entity to persist.
                Its ``id`` attribute is expected to be ``None`` at this point.

        Returns:
            MovementRecord: A new
            :class:`~monitoring.domain.entities.MovementRecord` instance that
            is a copy of the input enriched with the auto-assigned ``id`` from
            the database.
        """
        record = MovementRecordModel.create(
            device_id=movement_record.device_id,
            angle=movement_record.angle,
            created_at=movement_record.created_at,
        )
        return MovementRecord(
            movement_record.device_id,
            movement_record.angle,
            movement_record.created_at,
            record.id,
        )
