"""Shared pytest fixtures for the edge gateway tests."""
import pytest

from app.shared.infrastructure.database import db
from app.iam.infrastructure.models import Device
from app.detection.infrastructure.models import OutboxItem


@pytest.fixture
def memory_db():
    """Bind the shared models to a fresh in-memory SQLite database for a test."""
    db.init(":memory:")
    db.connect()
    db.create_tables([Device, OutboxItem])
    try:
        yield db
    finally:
        db.drop_tables([Device, OutboxItem])
        db.close()
