"""Repository implementation for the IAM bounded context.

Provides the persistence adapter that maps between the
:class:`~iam.domain.entities.Device` domain entity and the
:class:`~iam.infrastructure.models.Device` Peewee ORM model.

Following the Repository pattern, callers in the application layer work only
with domain entities and remain isolated from ORM and database details.
"""
from typing import Optional

import peewee

from app.iam.domain.entities import Device
from app.iam.infrastructure.models import Device as DeviceModel


class DeviceRepository:
    """Repository that persists and reconstructs :class:`~iam.domain.entities.Device` entities.

    All ORM-to-entity mapping is contained within this class, ensuring the
    domain layer has no dependency on Peewee.
    """

    @staticmethod
    def find_by_serial_and_api_key(serial_number: str, api_key: str) -> Optional[Device]:
        """Look up a kit by its serial number and API key.

        Queries the ``devices`` table for a row matching **both**
        ``serial_number`` and ``api_key``. Returns ``None`` when no match is
        found (rather than raising) so the domain service can apply the
        authentication rule without catching infrastructure exceptions.

        Args:
            serial_number (str): The kit serial to search for.
            api_key (str): The API key that must match the stored credential.

        Returns:
            Optional[Device]: The corresponding entity if a matching row exists;
            ``None`` otherwise.
        """
        try:
            device = DeviceModel.get(
                (DeviceModel.serial_number == serial_number) & (DeviceModel.api_key == api_key)
            )
            return Device(device.serial_number, device.api_key, device.created_at)
        except peewee.DoesNotExist:
            return None

    @staticmethod
    def get_or_create_test_device() -> Device:
        """Retrieve the default test kit, creating it if absent.

        Performs an idempotent ``get_or_create`` against the ``devices`` table.
        The test kit uses well-known, hard-coded credentials intended for local
        development and integration testing only — never for production.

        Returns:
            Device: The entity for ``serial_number='uflex-kit-001'``.
        """
        device, _ = DeviceModel.get_or_create(
            serial_number="uflex-kit-001",
            defaults={"api_key": "test-api-key-123", "created_at": "2026-05-29T23:23:00Z"},
        )
        return Device(device.serial_number, device.api_key, device.created_at)
