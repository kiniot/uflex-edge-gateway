"""Repository implementation for the Monitoring bounded context.

Provides the persistence adapter that maps between the
:class:`~monitoring.domain.entities.MovementRecord` domain entity and the
:class:`~monitoring.infrastructure.models.MovementRecord` Peewee ORM model.

Following the Repository pattern, callers in the application layer interact
only with domain entities and are shielded from ORM/database details.
"""
from dateutil.parser import parse

from monitoring.domain.entities import MovementRecord, SerieExecution
from monitoring.infrastructure.models import (
    MovementRecord as MovementRecordModel,
    SerieExecution as SerieExecutionModel,
)


def _coerce_datetime(value):
    """Return ``value`` as a ``datetime``, parsing it when SQLite hands back text."""
    if isinstance(value, str):
        return parse(value)
    return value


def _to_entity(model: MovementRecordModel) -> MovementRecord:
    """Map an ORM row to a domain entity, coercing ``created_at`` to ``datetime``.

    SQLite stores timestamps as text; depending on the stored format Peewee may
    hand the value back as a raw string.  This helper parses it so downstream
    domain logic (velocity, duration) can always rely on a real ``datetime``.
    """
    return MovementRecord(model.device_id, model.angle,
                          _coerce_datetime(model.created_at), model.id)


def _to_serie_entity(model: SerieExecutionModel) -> SerieExecution:
    """Map a ``serie_executions`` ORM row to a :class:`SerieExecution` entity."""
    return SerieExecution(
        serie_id=model.serie_id,
        device_id=model.device_id,
        started_at=_coerce_datetime(model.started_at),
        target_rom=model.target_rom,
        target_reps=model.target_reps,
        movement_type=model.movement_type,
        body_part=model.body_part,
        max_safe_angle=model.max_safe_angle,
        ended_at=_coerce_datetime(model.ended_at),
        status=model.status,
        reps_done=model.reps_done,
        good_reps=model.good_reps,
        bad_reps_incomplete=model.bad_reps_incomplete,
        bad_reps_unsafe=model.bad_reps_unsafe,
        avg_rom=model.avg_rom,
        min_angle=model.min_angle,
        max_angle=model.max_angle,
        valoracion=model.valoracion,
        dangerous_movement_detected=bool(model.dangerous_movement_detected),
        id=model.id,
    )


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

    @staticmethod
    def find_recent_by_device(device_id: str, limit: int = 200) -> list[MovementRecord]:
        """Return the most recent readings for one kit, oldest-to-newest.

        Fetches up to ``limit`` rows for ``device_id`` ordered by insertion
        order, then reverses them so the caller receives a chronological series
        suitable for time-based analysis (repetitions, angular velocity).

        Args:
            device_id (str): The kit whose readings are requested.
            limit (int): Maximum number of recent readings to return.

        Returns:
            list[MovementRecord]: Chronologically ordered domain entities
            (possibly empty).
        """
        query = (MovementRecordModel
                 .select()
                 .where(MovementRecordModel.device_id == device_id)
                 .order_by(MovementRecordModel.id.desc())
                 .limit(limit))
        records = [_to_entity(row) for row in query]
        records.reverse()
        return records

    @staticmethod
    def find_recent(limit: int = 100) -> list[MovementRecord]:
        """Return the most recent readings across all kits, newest-first.

        Args:
            limit (int): Maximum number of readings to return.

        Returns:
            list[MovementRecord]: Domain entities ordered newest-to-oldest.
        """
        query = (MovementRecordModel
                 .select()
                 .order_by(MovementRecordModel.id.desc())
                 .limit(limit))
        return [_to_entity(row) for row in query]

    @staticmethod
    def find_all_by_device(device_id: str) -> list[MovementRecord]:
        """Return every buffered reading for a kit, oldest-to-newest.

        Used when closing a series: the raw buffer holds only the current
        series' readings, so all of them feed the execution summary.

        Args:
            device_id (str): The kit whose buffered readings are requested.

        Returns:
            list[MovementRecord]: Chronologically ordered readings.
        """
        query = (MovementRecordModel
                 .select()
                 .where(MovementRecordModel.device_id == device_id)
                 .order_by(MovementRecordModel.id.asc()))
        return [_to_entity(row) for row in query]

    @staticmethod
    def delete_by_device(device_id: str) -> int:
        """Purge all buffered raw readings for a kit.

        Called when a series starts (clear stale buffer) and after it closes
        (the durable summary now holds the result, so the raw data is dropped).

        Args:
            device_id (str): The kit whose buffer is cleared.

        Returns:
            int: Number of rows deleted.
        """
        return (MovementRecordModel
                .delete()
                .where(MovementRecordModel.device_id == device_id)
                .execute())


class SerieExecutionRepository:
    """Repository that persists and reconstructs :class:`SerieExecution` aggregates.

    Backs the ``serie_executions`` table with the durable, chewed result of each
    executed therapy series.
    """

    @staticmethod
    def save(execution: SerieExecution) -> SerieExecution:
        """Insert a new (typically OPEN) series execution and assign its ``id``."""
        row = SerieExecutionModel.create(
            serie_id=execution.serie_id,
            device_id=execution.device_id,
            target_rom=execution.target_rom,
            target_reps=execution.target_reps,
            movement_type=execution.movement_type,
            body_part=execution.body_part,
            max_safe_angle=execution.max_safe_angle,
            started_at=execution.started_at,
            ended_at=execution.ended_at,
            status=execution.status,
            reps_done=execution.reps_done,
            good_reps=execution.good_reps,
            bad_reps_incomplete=execution.bad_reps_incomplete,
            bad_reps_unsafe=execution.bad_reps_unsafe,
            avg_rom=execution.avg_rom,
            min_angle=execution.min_angle,
            max_angle=execution.max_angle,
            valoracion=execution.valoracion,
            dangerous_movement_detected=execution.dangerous_movement_detected,
        )
        execution.id = row.id
        return execution

    @staticmethod
    def update(execution: SerieExecution) -> SerieExecution:
        """Persist the computed results of a now-closed series execution."""
        (SerieExecutionModel
         .update(
            ended_at=execution.ended_at,
            status=execution.status,
            reps_done=execution.reps_done,
            good_reps=execution.good_reps,
            bad_reps_incomplete=execution.bad_reps_incomplete,
            bad_reps_unsafe=execution.bad_reps_unsafe,
            avg_rom=execution.avg_rom,
            min_angle=execution.min_angle,
            max_angle=execution.max_angle,
            valoracion=execution.valoracion,
            dangerous_movement_detected=execution.dangerous_movement_detected,
         )
         .where(SerieExecutionModel.id == execution.id)
         .execute())
        return execution

    @staticmethod
    def find_open_by_device(device_id: str):
        """Return the most recent OPEN execution for a kit, or ``None``."""
        try:
            row = (SerieExecutionModel
                   .select()
                   .where((SerieExecutionModel.device_id == device_id) &
                          (SerieExecutionModel.status == "OPEN"))
                   .order_by(SerieExecutionModel.id.desc())
                   .get())
            return _to_serie_entity(row)
        except SerieExecutionModel.DoesNotExist:
            return None

    @staticmethod
    def discard_open_for_device(device_id: str) -> int:
        """Mark any lingering OPEN executions for a kit as DISCARDED.

        Guards against an unclosed previous series (e.g. a dropped connection)
        polluting a freshly started one.

        Returns:
            int: Number of executions discarded.
        """
        return (SerieExecutionModel
                .update(status="DISCARDED")
                .where((SerieExecutionModel.device_id == device_id) &
                       (SerieExecutionModel.status == "OPEN"))
                .execute())

    @staticmethod
    def find_by_id(execution_id: int):
        """Return the execution with the given id, or ``None`` when absent."""
        try:
            return _to_serie_entity(SerieExecutionModel.get_by_id(execution_id))
        except SerieExecutionModel.DoesNotExist:
            return None
