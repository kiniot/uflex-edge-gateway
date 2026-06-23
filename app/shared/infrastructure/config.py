"""Runtime configuration for the uFlex Edge Gateway.

Centralizes the settings the edge needs to reach the cloud backend. Values come
from environment variables so secrets (the edge service-account credential) are
never hard-coded or committed; they are provisioned per home at install time.

Environment variables:
    UFLEX_BACKEND_URL: Base URL of the uFlex REST API (scheme://host:port),
        without the ``/api/v1`` suffix. Defaults to ``http://localhost:8080``.
    UFLEX_EDGE_EMAIL: Login email of this edge's service account.
    UFLEX_EDGE_PASSWORD: Password of this edge's service account.
    UFLEX_KIT_SERIAL: Serial of the single kit this edge serves (1 edge ↔ 1 kit).
        Defaults to ``uflex-kit-001`` (the dev test kit).
    UFLEX_EDGE_LAN_PORT: TCP port the edge serves on the LAN, used to build the LAN URL it
        reports to the backend for mobile rendezvous. Defaults to ``5050``.
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class EdgeConfig:
    """Immutable view of the edge's runtime configuration.

    Attributes:
        backend_url (str): Base URL of the backend, trailing slash stripped.
        edge_email (str): Service-account login email.
        edge_password (str): Service-account password.
        kit_serial (str): Serial of the kit this edge serves (for correlation).
        lan_port (int): TCP port the edge serves on the LAN (for the reported LAN URL).
        request_timeout_seconds (float): Per-request HTTP timeout.
        poll_interval_seconds (float): Cadence of the active-session poller.
        forward_interval_seconds (float): Cadence of the outbox forwarding worker.
    """

    backend_url: str
    edge_email: str
    edge_password: str
    kit_serial: str
    lan_port: int = 5050
    request_timeout_seconds: float = 10.0
    poll_interval_seconds: float = 3.0
    forward_interval_seconds: float = 1.0

    @staticmethod
    def from_env() -> "EdgeConfig":
        """Build an :class:`EdgeConfig` from environment variables.

        Returns:
            EdgeConfig: The resolved configuration. ``edge_email`` /
            ``edge_password`` may be empty strings when unset; the backend
            client validates their presence lazily on first use.
        """
        backend_url = os.environ.get("UFLEX_BACKEND_URL", "http://localhost:8080").rstrip("/")
        edge_email = os.environ.get("UFLEX_EDGE_EMAIL", "")
        edge_password = os.environ.get("UFLEX_EDGE_PASSWORD", "")
        kit_serial = os.environ.get("UFLEX_KIT_SERIAL", "uflex-kit-001")
        lan_port = int(os.environ.get("UFLEX_EDGE_LAN_PORT", "5050"))
        return EdgeConfig(
            backend_url=backend_url,
            edge_email=edge_email,
            edge_password=edge_password,
            kit_serial=kit_serial,
            lan_port=lan_port,
        )
