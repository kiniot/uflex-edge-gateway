"""Application services for the IAM bounded context.

Application services orchestrate use-cases by coordinating domain objects and
repositories.  They contain no domain logic themselves; all business rules live
in the domain layer.
"""
from typing import Optional

from iam.domain.entities import Device
from iam.domain.services import AuthService
from iam.infrastructure.repositories import DeviceRepository


class AuthApplicationService:
    """Application service that orchestrates device-authentication use-cases.

    Coordinates the :class:`~iam.infrastructure.repositories.DeviceRepository`
    (for reading kit credentials) and the
    :class:`~iam.domain.services.AuthService` (for applying the authentication
    business rule).
    """

    def __init__(self):
        """Initialise the service with its required collaborators."""
        self.device_repository = DeviceRepository()
        self.auth_service = AuthService()

    def authenticate(self, device_id: str, api_key: str) -> bool:
        """Authenticate an IoT Kit by its ID and API key.

        Looks up the device in the repository using the supplied credentials.
        The domain service then evaluates whether the result constitutes a
        successful authentication.

        Args:
            device_id (str): Unique identifier of the kit (e.g.
                ``'uflex-kit-001'``).
            api_key (str): The secret API key paired with the kit,
                typically provided in the ``X-API-Key`` request header.

        Returns:
            bool: ``True`` if a device with the given ``device_id`` and
            ``api_key`` exists in the repository; ``False`` otherwise.
        """
        device: Optional[Device] = self.device_repository.find_by_id_and_api_key(device_id, api_key)
        return self.auth_service.authenticate(device)

    def get_or_create_test_device(self) -> Device:
        """Retrieve the default test kit, creating it if it does not exist.

        Intended for development and local testing only.  Delegates to the
        repository to perform an idempotent ``get_or_create`` operation against
        the ``devices`` table.

        Returns:
            Device: The :class:`~iam.domain.entities.Device` entity for the
            pre-configured test kit (``device_id='uflex-kit-001'``).
        """
        return self.device_repository.get_or_create_test_device()
