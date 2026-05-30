"""Application services for the Monitoring bounded context.

Application services sit between the interface layer and the domain layer.
They orchestrate use-cases by coordinating domain services, domain entities,
and repositories without containing domain logic themselves.
"""

from monitoring.domain.entities import MovementRecord
from monitoring.domain.services import MovementRecordService
from monitoring.infrastructure.repositories import MovementRecordRepository
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
        record = self.movement_record_service.create_record(device_id, angle, created_at)
        return self.movement_record_repository.save(record)
