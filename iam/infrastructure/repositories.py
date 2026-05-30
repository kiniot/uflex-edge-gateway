"""Repository implementation for the IAM bounded context.

Provides the persistence adapter that maps between the
:class:`~iam.domain.entities.Device` domain entity and the
:class:`~iam.infrastructure.models.Device` Peewee ORM model.

Following the Repository pattern, callers in the application layer work only
with domain entities and remain isolated from ORM and database details.
"""
from typing import Optional

import peewee

from iam.domain.entities import Device
from iam.infrastructure.models import Device as DeviceModel


class DeviceRepository:
    """Repository that persists and reconstructs :class:`~iam.domain.entities.Device` entities.

    Implements the collection-like interface expected by application services.
    All ORM-to-entity mapping is contained within this class, ensuring the
    domain layer has no dependency on Peewee.
    """

    @staticmethod
    def find_by_id_and_api_key(device_id: str, api_key: str) -> Optional[Device]:
        """Look up a kit by its identifier and API key.

        Queries the ``devices`` table for a row matching **both** ``device_id``
        and ``api_key``.  Returning ``None`` when no match is found (rather
        than raising) lets the domain service apply the authentication rule
        without catching infrastructure exceptions.

        Args:
            device_id (str): The kit identifier to search for.
            api_key (str): The API key that must match the stored credential.

        Returns:
            Optional[Device]: The corresponding :class:`~iam.domain.entities.Device`
            entity if a matching row exists; ``None`` otherwise.
        """
        try:
            device = DeviceModel.get(
                (DeviceModel.device_id == device_id) & (DeviceModel.api_key == api_key)
            )
            return Device(device.device_id, device.api_key, device.created_at)
        except peewee.DoesNotExist:
            return None

    @staticmethod
    def get_or_create_test_device() -> Device:
        """Retrieve the default test kit, creating it if absent.

        Performs an idempotent ``get_or_create`` against the ``devices``
        table.  The test kit uses well-known, hard-coded credentials intended
        for local development and integration testing only — these credentials
        must never be used in a production environment.

        Returns:
            Device: The :class:`~iam.domain.entities.Device` entity for
            ``device_id='uflex-kit-001'``.
        """
        device, _ = DeviceModel.get_or_create(
            device_id="uflex-kit-001",
            defaults={"api_key": "test-api-key-123", "created_at": "2026-05-29T23:23:00Z"},
        )
        return Device(device.device_id, device.api_key, device.created_at)
