"""Unit tests for the ForwardingWorker drain: a poison entry must not block the FIFO queue."""
from app.detection.application.forwarding import ForwardingWorker
from app.detection.infrastructure.backend_forwarder import ForwardOutcome
from app.detection.infrastructure.repositories import OutboxRepository


class _ScriptedForwarder:
    """Returns an outcome per entry, keyed by edge_sequence_id."""

    def __init__(self, outcomes):
        self._outcomes = outcomes
        self.seen = []

    def forward(self, entry):
        self.seen.append(entry.edge_sequence_id)
        return self._outcomes[entry.edge_sequence_id]


def test_drop_entry_does_not_block_the_queue(memory_db):
    repo = OutboxRepository()
    repo.enqueue("repetition", "kit", "sess", "ser", "poison", {"n": 1})   # permanent 4xx
    repo.enqueue("repetition", "kit", "sess", "ser", "ok-1", {"n": 2})
    repo.enqueue("repetition", "kit", "sess", "ser", "ok-2", {"n": 3})
    forwarder = _ScriptedForwarder({
        "poison": ForwardOutcome.DROP,
        "ok-1": ForwardOutcome.SENT,
        "ok-2": ForwardOutcome.SENT,
    })
    worker = ForwardingWorker(repo, forwarder)

    worker._drain_once()

    # The poison entry is quarantined and the two behind it still forwarded (no head-of-line block).
    assert forwarder.seen == ["poison", "ok-1", "ok-2"]
    assert repo.count_pending() == 0
    assert repo.count_failed() == 1


def test_retry_entry_stops_the_pass_and_preserves_order(memory_db):
    repo = OutboxRepository()
    repo.enqueue("repetition", "kit", "sess", "ser", "transient", {"n": 1})  # 5xx/network
    repo.enqueue("repetition", "kit", "sess", "ser", "behind", {"n": 2})
    forwarder = _ScriptedForwarder({
        "transient": ForwardOutcome.RETRY,
        "behind": ForwardOutcome.SENT,
    })
    worker = ForwardingWorker(repo, forwarder)

    worker._drain_once()

    # A transient failure stops the pass to preserve FIFO order; nothing behind it is sent yet.
    assert forwarder.seen == ["transient"]
    assert repo.count_pending() == 2
    assert repo.count_failed() == 0
