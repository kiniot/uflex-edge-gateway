"""Domain services for the IAM bounded context.

Domain services express business behavior that does not fit neatly inside a
single entity.  ``AuthService`` encapsulates the authentication invariant for
the IAM bounded context: a kit is considered authenticated when it exists in
the repository (i.e. it was found by matching both ``device_id`` and
``api_key``).
"""
from typing import Optional

from app.iam.domain.entities import Device


class AuthService:
    """Domain service that determines whether a device (IoT Kit) is authenticated.

    The authentication rule is deliberately kept simple: a ``Device`` object
    that was successfully retrieved from the repository is, by definition,
    authenticated.  Absent or unrecognized credentials result in ``None``
    being passed to this service, which returns ``False``.
    """

    @staticmethod
    def authenticate(device: Optional[Device]) -> bool:
        """Determine whether the given device is authenticated.

        The :class:`~iam.infrastructure.repositories.DeviceRepository` returns
        ``None`` when no device matches the supplied credentials; a non-``None``
        value indicates that the ``device_id`` / ``api_key`` pair is valid.

        Args:
            device (Optional[Device]): The device entity returned by the
                repository look-up, or ``None`` if no matching device was found.

        Returns:
            bool: ``True`` if ``device`` is not ``None`` (authentication
            succeeds); ``False`` otherwise.
        """
        return device is not None
