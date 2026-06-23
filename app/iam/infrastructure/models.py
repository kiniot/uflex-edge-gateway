"""Peewee ORM model for the IAM bounded context.

Defines the ``devices`` database table used to persist
:class:`~iam.domain.entities.Device` aggregate roots.  This module belongs
to the infrastructure layer; it must not be imported directly by the domain
or application layers — access is mediated through the repository.
"""
from peewee import Model, CharField, DateTimeField

from app.shared.infrastructure.database import db


class Device(Model):
    """ORM mapping for the ``devices`` table.

    Each row represents a registered uFlex IoT Kit and its associated API key,
    which is used to authenticate inbound requests.

    Attributes:
        serial_number (CharField): Natural primary key — the kit's cross-service
            serial number (e.g. ``'uflex-kit-001'``).
        api_key (CharField): Secret key paired with the kit, checked on every
            authenticated API call.
        created_at (DateTimeField): UTC timestamp recording when the kit was
            first registered.
    """

    serial_number = CharField(primary_key=True)
    api_key       = CharField()
    created_at    = DateTimeField()

    class Meta:
        """Peewee metadata: binds the model to the shared database and names the table."""

        database   = db
        table_name = 'devices'
