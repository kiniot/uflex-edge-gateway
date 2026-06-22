"""Composition root for the Detection bounded context.

Wires the shared in-memory state and services used by both the HTTP interface
(sample ingest, debug view) and the background runtime (correlation poller +
forwarding worker), so every part operates on the *same* instances.
"""
import logging

from app.detection.application.correlation import CorrelationPoller
from app.detection.application.forwarding import ForwardingWorker
from app.detection.application.services import DebugViewService, SampleIngestService
from app.detection.application.state import EdgeRuntimeState
from app.detection.infrastructure.backend_forwarder import BackendForwarder
from app.detection.infrastructure.repositories import OutboxRepository
from app.shared.infrastructure.backend_client import BackendClient
from app.shared.infrastructure.config import EdgeConfig

logger = logging.getLogger(__name__)

# Shared singletons (one edge process).
state = EdgeRuntimeState()
outbox_repository = OutboxRepository()
ingest_service = SampleIngestService(state, outbox_repository)
debug_service = DebugViewService(state)

_threads: list = []


def start_background(config: EdgeConfig = None) -> None:
    """Start the correlation poller and forwarding worker (idempotent)."""
    global _threads
    if _threads:
        return
    config = config or EdgeConfig.from_env()
    client = BackendClient(config)
    forwarder = BackendForwarder(client)
    poller = CorrelationPoller(config.kit_serial, client, state, config.poll_interval_seconds)
    worker = ForwardingWorker(outbox_repository, forwarder, config.forward_interval_seconds)
    poller.start()
    worker.start()
    _threads = [poller, worker]
    logger.info("Edge background runtime started (kit=%s)", config.kit_serial)
