"""Application services for the IAM bounded context.

Application services orchestrate use-cases by coordinating domain objects and
repositories.  They contain no domain logic themselves; all business rules live
in the domain layer.
"""
from typing import Optional

from app.iam.domain.entities import Device
from app.iam.domain.services import AuthService
from app.iam.infrastructure.repositories import DeviceRepository


class AuthApplicationService:
    """Application service that orchestrates device-authentication use-cases."""

    def __init__(self):
        """Initialise the service with its required collaborators."""
        self.device_repository = DeviceRepository()
        self.auth_service = AuthService()

    def authenticate(self, serial_number: str, api_key: str) -> bool:
        """Authenticate an IoT Kit by its serial number and API key.

        Args:
            serial_number (str): Cross-service identifier of the kit (e.g.
                ``'uflex-kit-001'``).
            api_key (str): The secret API key paired with the kit, provided in
                the ``X-API-Key`` request header.

        Returns:
            bool: ``True`` if a device with the given ``serial_number`` and
            ``api_key`` exists; ``False`` otherwise.
        """
        device: Optional[Device] = self.device_repository.find_by_serial_and_api_key(serial_number, api_key)
        return self.auth_service.authenticate(device)

    def get_or_create_test_device(self) -> Device:
        """Retrieve the default test kit, creating it if it does not exist.

        Intended for development and local testing only.

        Returns:
            Device: The entity for the pre-configured test kit
            (``serial_number='uflex-kit-001'``).
        """
        return self.device_repository.get_or_create_test_device()
