"""Unit tests for the durable outbox (FIFO + status transitions)."""
from app.detection.infrastructure.repositories import OutboxRepository


def test_fifo_order_and_mark_sent(memory_db):
    repo = OutboxRepository()
    repo.enqueue("repetition", "kit", "sess", "ser", "uuid-1", {"n": 1})
    second = repo.enqueue("repetition", "kit", "sess", "ser", "uuid-2", {"n": 2})
    repo.enqueue("repetition", "kit", "sess", "ser", "uuid-3", {"n": 3})

    pending = repo.find_pending()
    assert [p.edge_sequence_id for p in pending] == ["uuid-1", "uuid-2", "uuid-3"]
    assert repo.count_pending() == 3
    # Payload round-trips through JSON.
    assert pending[1].payload == {"n": 2}

    repo.mark_sent(pending[0].id)
    repo.mark_sent(second.id)

    remaining = repo.find_pending()
    assert [p.edge_sequence_id for p in remaining] == ["uuid-3"]
    assert repo.count_pending() == 1


def test_mark_failed_quarantines_and_excludes_from_pending(memory_db):
    repo = OutboxRepository()
    poison = repo.enqueue("repetition", "kit", "sess", "ser", "uuid-1", {"n": 1})
    repo.enqueue("repetition", "kit", "sess", "ser", "uuid-2", {"n": 2})

    repo.mark_failed(poison.id)

    # The quarantined entry drops out of the FIFO so it can't block the rest, but is not deleted.
    assert [p.edge_sequence_id for p in repo.find_pending()] == ["uuid-2"]
    assert repo.count_pending() == 1
    assert repo.count_failed() == 1
