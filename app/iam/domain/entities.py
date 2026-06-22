"""Domain entities for the IAM bounded context.

This module defines the aggregate root for the IAM bounded context.
Entities carry identity across their lifetime and encapsulate state that
is only modified by domain services enforcing business invariants.
"""
from datetime import datetime


class Device:
    """Aggregate root representing a registered uFlex IoT Kit.

    A ``Device`` is the core identity object in the IAM bounded context. It is
    identified by its ``serial_number`` (the kit's cross-service identity, equal
    to the backend's ``serialNumber`` and the value the embedded firmware reports)
    and authenticated via its paired ``api_key``.

    Attributes:
        serial_number (str): Immutable, unique cross-service identifier for the
            kit (e.g. ``'uflex-kit-001'``). Natural key of the device.
        api_key (str): Secret key used to authenticate HTTP requests originating
            from this kit, transmitted via the ``X-API-Key`` header.
        created_at (datetime): UTC timestamp recording when the kit was first
            registered in the system.
    """

    def __init__(self, serial_number: str, api_key: str, created_at: datetime):
        """Initialise a Device aggregate root.

        Args:
            serial_number (str): Unique cross-service identifier for the kit.
            api_key (str): Secret API key used for request authentication.
            created_at (datetime): UTC timestamp of kit registration.
        """
        self.serial_number = serial_number
        self.api_key = api_key
        self.created_at = created_at
