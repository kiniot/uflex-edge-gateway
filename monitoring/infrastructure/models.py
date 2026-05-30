"""Peewee ORM model for the Monitoring bounded context.

Defines the ``movement_records`` database table structure used to persist
:class:`~monitoring.domain.entities.MovementRecord` domain entities.  This
module belongs to the infrastructure layer and must not be referenced directly
from the domain or application layers; access is mediated through the
repository.
"""
from peewee import Model, AutoField, FloatField, CharField, DateTimeField

from shared.infrastructure.database import db


class MovementRecord(Model):
    """ORM mapping for the ``movement_records`` table.

    Each row represents a single joint flexion reading submitted by a
    registered uFlex IoT Kit.

    Attributes:
        id (AutoField): Auto-incrementing integer primary key assigned by the
            database on insert.
        device_id (CharField): Reference to the kit that produced the reading.
            Stored as a plain string (not a FK constraint) to keep the bounded
            contexts loosely coupled.
        angle (FloatField): Joint flexion angle measured in degrees.
        created_at (DateTimeField): UTC timestamp of when the reading was
            captured by the kit.
    """

    id = AutoField()
    device_id = CharField()
    angle = FloatField()
    created_at = DateTimeField()

    class Meta:
        """Peewee metadata: binds the model to the shared database and names the table."""

        database = db
        table_name = 'movement_records'
