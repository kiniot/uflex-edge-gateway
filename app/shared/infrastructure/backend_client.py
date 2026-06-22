"""Authenticated HTTP client for the uFlex cloud backend.

This is the edge's first outbound client. It implements the machine-to-machine
half of the *hybrid* auth scheme: the durable credential is the edge service
account (email + password); the bearer token that actually travels on each
request is a short-lived JWT obtained via the backend ``sign-in`` endpoint.

Behaviour:
    - **Lazy sign-in:** the JWT is fetched on the first request, not at startup,
      so the edge boots even when the backend is unreachable.
    - **In-memory token:** the JWT lives only in memory; after a restart the edge
      simply signs in again. The plaintext credential stays in config/env.
    - **Refresh on 401:** an expired/invalid token triggers a single re-sign-in
      and one retry.
    - **Single-flight:** concurrent 401s collapse into a single re-sign-in (a
      lock guards token mutation), avoiding a stampede of sign-in calls.

The forwarding use cases (per-rep ingestion, compensatory movements) build on
top of this client; here we only establish the authenticated channel.
"""
import threading
from typing import Optional

import requests

from app.shared.infrastructure.config import EdgeConfig

_SIGN_IN_PATH = "/api/v1/authentication/sign-in"


class BackendAuthError(Exception):
    """Raised when the edge cannot obtain a bearer token from the backend."""


class BackendClient:
    """Thread-safe, self-authenticating HTTP client for the backend.

    Wraps a :class:`requests.Session`, attaching the edge's bearer token to every
    request and transparently re-authenticating once on a ``401``.
    """

    def __init__(self, config: Optional[EdgeConfig] = None):
        """Initialise the client.

        Args:
            config (EdgeConfig, optional): Configuration to use. Defaults to one
                built from environment variables via :meth:`EdgeConfig.from_env`.
        """
        self._config = config or EdgeConfig.from_env()
        self._session = requests.Session()
        self._token: Optional[str] = None
        self._lock = threading.Lock()

    def get(self, path: str, **kwargs) -> requests.Response:
        """Perform an authenticated ``GET`` against ``path`` (e.g. ``/api/v1/...``)."""
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> requests.Response:
        """Perform an authenticated ``POST`` against ``path`` (e.g. ``/api/v1/...``)."""
        return self.request("POST", path, **kwargs)

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Perform an authenticated request, refreshing the token once on ``401``.

        Args:
            method (str): HTTP method (``GET``, ``POST``, ...).
            path (str): Path beginning with ``/`` (joined to the backend base URL).
            **kwargs: Forwarded to :meth:`requests.Session.request`.

        Returns:
            requests.Response: The backend response (the post-refresh one when a
            ``401`` was retried).
        """
        token = self._ensure_token()
        response = self._send(method, path, token, **kwargs)
        if response.status_code == 401:
            token = self._refresh(token)
            response = self._send(method, path, token, **kwargs)
        return response

    def _send(self, method: str, path: str, token: str, **kwargs) -> requests.Response:
        """Issue a single request with the given bearer token attached."""
        url = self._config.backend_url + path
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = f"Bearer {token}"
        headers.setdefault("Accept", "application/json")
        return self._session.request(
            method,
            url,
            headers=headers,
            timeout=self._config.request_timeout_seconds,
            **kwargs,
        )

    def _ensure_token(self) -> str:
        """Return the current token, signing in lazily (single-flight) if needed."""
        if self._token is None:
            with self._lock:
                if self._token is None:
                    self._sign_in()
        return self._token

    def _refresh(self, stale_token: str) -> str:
        """Re-sign-in once, unless another thread already replaced ``stale_token``."""
        with self._lock:
            if self._token == stale_token or self._token is None:
                self._sign_in()
        return self._token

    def _sign_in(self) -> None:
        """Exchange the service-account credential for a fresh JWT.

        Caller must hold ``self._lock``. Stores the token in memory.

        Raises:
            BackendAuthError: When credentials are missing or the backend does
                not return a token.
        """
        if not self._config.edge_email or not self._config.edge_password:
            raise BackendAuthError(
                "Edge credentials are not configured (UFLEX_EDGE_EMAIL / UFLEX_EDGE_PASSWORD)"
            )
        url = self._config.backend_url + _SIGN_IN_PATH
        try:
            response = self._session.post(
                url,
                json={"email": self._config.edge_email, "password": self._config.edge_password},
                headers={"Accept": "application/json"},
                timeout=self._config.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise BackendAuthError(f"Sign-in request to backend failed: {exc}") from exc
        if response.status_code != 200:
            raise BackendAuthError(
                f"Sign-in rejected by backend (HTTP {response.status_code})"
            )
        token = response.json().get("token")
        if not token:
            raise BackendAuthError("Sign-in response did not contain a token")
        self._token = token
