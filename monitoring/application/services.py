"""Application services for the Monitoring bounded context.

Application services sit between the interface layer and the domain layer.
They orchestrate use-cases by coordinating domain services, domain entities,
and repositories without containing domain logic themselves.
"""

import uuid
from datetime import datetime, timezone

from monitoring.domain.entities import MovementRecord, SerieExecution
from monitoring.domain.services import MovementRecordService, MovementAnalysisService
from monitoring.infrastructure.repositories import (
    MovementRecordRepository,
    SerieExecutionRepository,
)
from iam.infrastructure.repositories import DeviceRepository


class MovementRecordApplicationService:
    """Application service that orchestrates the *create movement record* use-case.

    Responsibilities:

    1. Cross-context validation – delegates to the IAM
       :class:`~iam.infrastructure.repositories.DeviceRepository` to verify
       that the requesting kit is registered and the supplied API key is
       valid.
    2. Domain logic – delegates to
       :class:`~monitoring.domain.services.MovementRecordService` to validate
       the raw sensor values and construct a
       :class:`~monitoring.domain.entities.MovementRecord` entity.
    3. Persistence – delegates to
       :class:`~monitoring.infrastructure.repositories.MovementRecordRepository`
       to persist the entity and return the saved aggregate with its assigned
       identity.
    """

    def __init__(self):
        """Initialize the service with its required collaborators."""
        self.movement_record_repository = MovementRecordRepository()
        self.movement_record_service = MovementRecordService()
        self.serie_execution_repository = SerieExecutionRepository()
        self.device_repository = DeviceRepository()

    def create_movement_record(self, device_id: str, angle: float, created_at: str, api_key: str) -> MovementRecord:
        """Execute the *create movement record* use-case.

        Validates that the kit identified by ``device_id`` is registered and
        that the supplied ``api_key`` matches the stored credential before
        delegating record creation to the domain service and persisting the
        result.

        Args:
            device_id (str): Identifier of the kit submitting the reading.
            angle (float): Joint flexion angle in degrees.
            created_at (str): ISO 8601 timestamp of the reading.  Passed
                directly to the domain service, which also accepts ``None``
                to default to the current UTC time.
            api_key (str): The value of the ``X-API-Key`` request header used
                to authenticate the kit.

        Returns:
            MovementRecord: The persisted
            :class:`~monitoring.domain.entities.MovementRecord` entity
            populated with its assigned ``id``.

        Raises:
            ValueError: If no kit matches the given ``device_id`` / ``api_key``
                combination, or if the domain service rejects the sensor values
                (invalid angle or malformed timestamp).
        """
        # Cross-context guard: verify kit identity via the IAM repository.
        if not self.device_repository.find_by_id_and_api_key(device_id, api_key):
            raise ValueError("Device not found")
        # Stamp the reading with the kit's open series so the raw buffer links to
        # its processed result; ``None`` when no series is open.
        open_execution = self.serie_execution_repository.find_open_by_device(device_id)
        serie_id = open_execution.serie_id if open_execution else None
        record = self.movement_record_service.create_record(device_id, angle, created_at, serie_id)
        return self.movement_record_repository.save(record)


class MovementAnalysisApplicationService:
    """Application service that orchestrates the *read* and *analyse* use-cases.

    It pulls stored readings from the repository and delegates the heavy
    lifting to :class:`~monitoring.domain.services.MovementAnalysisService`,
    returning the digested summary that the gateway exposes to clients and
    (in a later iteration) forwards to the backend.
    """

    def __init__(self):
        """Initialize the service with its required collaborators."""
        self.movement_record_repository = MovementRecordRepository()
        self.movement_analysis_service = MovementAnalysisService()

    def get_recent_records(self, device_id: str = None, limit: int = 100) -> list[MovementRecord]:
        """Return recent raw readings, optionally filtered by kit.

        Args:
            device_id (str, optional): When given, restrict results to this
                kit.  When ``None``, return readings across all kits.
            limit (int): Maximum number of readings to return.

        Returns:
            list[MovementRecord]: The matching readings.
        """
        if device_id:
            return self.movement_record_repository.find_recent_by_device(device_id, limit)
        return self.movement_record_repository.find_recent(limit)

    def analyze_device(self, device_id: str, limit: int = 200,
                       target_rom: float = None, max_safe_angle: float = None) -> dict:
        """Produce the digested movement summary for one kit.

        Args:
            device_id (str): The kit to analyse.
            limit (int): Maximum number of recent readings to feed the analysis.
            target_rom (float, optional): Backend-defined range-of-motion goal.
            max_safe_angle (float, optional): Backend-defined safety ceiling.

        Returns:
            dict: The summary returned by the domain service, enriched with the
            ``device_id`` it describes.
        """
        samples = self.movement_record_repository.find_recent_by_device(device_id, limit)
        summary = self.movement_analysis_service.analyze(samples, target_rom, max_safe_angle)
        summary["device_id"] = device_id
        return summary


class SerieExecutionApplicationService:
    """Application service that orchestrates the series-execution lifecycle.

    Coordinates the IAM guard, the raw-reading buffer and the analysis domain
    service across the series use-cases: *start* a series, *end* it (classify
    repetitions, aggregate and persist the result, keeping the linked raw
    readings), *read* a stored result and *list* the processed history.
    """

    def __init__(self):
        """Initialize the service with its required collaborators."""
        self.serie_execution_repository = SerieExecutionRepository()
        self.movement_record_repository = MovementRecordRepository()
        self.movement_analysis_service = MovementAnalysisService()
        self.device_repository = DeviceRepository()

    def start_serie(self, device_id: str, api_key: str, serie_id: str = None,
                    target_rom: float = None, target_reps: int = None,
                    movement_type: str = None, body_part: str = None,
                    max_safe_angle: float = None) -> SerieExecution:
        """Open a new series execution for a kit.

        Verifies the kit identity and discards any lingering open execution, then
        persists an OPEN :class:`SerieExecution` capturing the target parameters.
        A ``serie_id`` is generated when the caller does not supply one so the
        incoming readings can always be linked to this series.

        Raw readings are no longer purged here: prior series' readings are kept
        (linked to their own ``serie_id``) so the processed history stays
        inspectable.

        Raises:
            ValueError: If the kit / API key pair is not registered.
        """
        if not self.device_repository.find_by_id_and_api_key(device_id, api_key):
            raise ValueError("Device not found")
        self.serie_execution_repository.discard_open_for_device(device_id)
        if not serie_id:
            serie_id = f"serie-{uuid.uuid4().hex[:8]}"
        execution = SerieExecution(
            serie_id=serie_id,
            device_id=device_id,
            started_at=datetime.now(timezone.utc),
            target_rom=target_rom,
            target_reps=target_reps,
            movement_type=movement_type,
            body_part=body_part,
            max_safe_angle=max_safe_angle,
            status="OPEN",
        )
        return self.serie_execution_repository.save(execution)

    def end_serie(self, device_id: str, api_key: str):
        """Close the open series for a kit and compute its result.

        Reads the readings stamped with this series' ``serie_id``, classifies
        every repetition, aggregates the outcome onto the execution and persists
        it as CLOSED.  The raw readings are kept (not purged) so the raw buffer
        and its processed result can be inspected side by side.

        Returns:
            tuple[SerieExecution, list[dict]]: The closed execution and the
            per-repetition breakdown.

        Raises:
            ValueError: If the kit is not registered or has no open series.
        """
        if not self.device_repository.find_by_id_and_api_key(device_id, api_key):
            raise ValueError("Device not found")
        execution = self.serie_execution_repository.find_open_by_device(device_id)
        if not execution:
            raise ValueError("No open series for device")

        samples = self.movement_record_repository.find_by_serie_id(execution.serie_id)
        summary = self.movement_analysis_service.summarize_execution(
            samples, execution.target_rom, execution.target_reps, execution.max_safe_angle
        )

        execution.ended_at = datetime.now(timezone.utc)
        execution.status = "CLOSED"
        execution.reps_done = summary["reps_done"]
        execution.good_reps = summary["good_reps"]
        execution.bad_reps_incomplete = summary["bad_reps_incomplete"]
        execution.bad_reps_unsafe = summary["bad_reps_unsafe"]
        execution.avg_rom = summary["avg_rom"]
        execution.min_angle = summary["min_angle"]
        execution.max_angle = summary["max_angle"]
        execution.valoracion = summary["valoracion"]
        execution.dangerous_movement_detected = summary["dangerous_movement_detected"]

        self.serie_execution_repository.update(execution)
        return execution, summary["repetitions"]

    def get_result(self, execution_id: int):
        """Return a stored series execution by id, or ``None`` when absent."""
        return self.serie_execution_repository.find_by_id(execution_id)

    def list_executions(self, device_id: str = None, limit: int = 50) -> list[SerieExecution]:
        """Return recent series executions (the processed history), newest-first.

        Args:
            device_id (str, optional): Restrict to one kit when given.
            limit (int): Maximum executions to return.

        Returns:
            list[SerieExecution]: The processed results the backend would consume.
        """
        return self.serie_execution_repository.find_recent(device_id, limit)
