"""Peewee ORM model for the Monitoring bounded context.

Defines the ``movement_records`` database table structure used to persist
:class:`~monitoring.domain.entities.MovementRecord` domain entities.  This
module belongs to the infrastructure layer and must not be referenced directly
from the domain or application layers; access is mediated through the
repository.
"""
from peewee import (
    Model, AutoField, FloatField, CharField, DateTimeField,
    IntegerField, BooleanField,
)

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
        serie_id (CharField): Reference to the open series this reading belongs
            to (the ``serie_id`` of the OPEN ``serie_executions`` row at ingest
            time).  ``null`` when the reading arrived with no series open.  This
            is what links the raw buffer to its chewed result, so both tables can
            be filtered by the same ``serie_id``.
        angle (FloatField): Joint flexion angle measured in degrees.
        created_at (DateTimeField): UTC timestamp of when the reading was
            captured by the kit.
    """

    id = AutoField()
    device_id = CharField()
    serie_id = CharField(null=True)
    angle = FloatField()
    created_at = DateTimeField()

    class Meta:
        """Peewee metadata: binds the model to the shared database and names the table."""

        database = db
        table_name = 'movement_records'


class SerieExecution(Model):
    """ORM mapping for the ``serie_executions`` table.

    Each row is the durable, chewed result of one executed therapy series:
    repetition outcome (good/bad), achieved range of motion and quality score.
    Raw ``movement_records`` are a transient buffer; this table is what persists
    and is forwarded to the backend.
    """

    id = AutoField()
    serie_id = CharField(null=True)
    device_id = CharField()
    target_rom = FloatField(null=True)
    target_reps = IntegerField(null=True)
    movement_type = CharField(null=True)
    body_part = CharField(null=True)
    max_safe_angle = FloatField(null=True)
    started_at = DateTimeField()
    ended_at = DateTimeField(null=True)
    status = CharField()
    reps_done = IntegerField(default=0)
    good_reps = IntegerField(default=0)
    bad_reps_incomplete = IntegerField(default=0)
    bad_reps_unsafe = IntegerField(default=0)
    avg_rom = FloatField(null=True)
    min_angle = FloatField(null=True)
    max_angle = FloatField(null=True)
    valoracion = FloatField(null=True)
    dangerous_movement_detected = BooleanField(default=False)

    class Meta:
        """Peewee metadata: binds the model to the shared database and names the table."""

        database = db
        table_name = 'serie_executions'
