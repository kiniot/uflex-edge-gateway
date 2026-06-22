"""Interface (REST API) layer for the IAM bounded context.

Exposes a Flask Blueprint (``iam_api``) and shared authentication helpers used
by other bounded contexts to guard their own endpoints. This layer owns no
domain or business logic; it handles HTTP request/response concerns and
delegates to the application service.
"""
from typing import Optional

from flask import Blueprint, request, jsonify

from app.iam.application.services import AuthApplicationService

iam_api = Blueprint("iam_api", __name__)

# Module-level singleton — instantiated once per worker process.
auth_service = AuthApplicationService()


def kit_serial_from_request() -> Optional[str]:
    """Extract the kit serial from the JSON body of the current request.

    Accepts ``serial_number`` (the current contract) and, for backward
    compatibility with firmware that has not migrated yet, ``device_id``.

    Returns:
        Optional[str]: The serial, or ``None`` when neither key is present.
    """
    data = request.json if request.is_json else None
    if not data:
        return None
    return data.get("serial_number") or data.get("device_id")


def authenticate_request():
    """Validate the kit identity for an incoming HTTP request.

    Extracts the kit serial from the JSON body (``serial_number`` or legacy
    ``device_id``) and ``X-API-Key`` from the headers, then verifies the pair
    against the device registry. Intended to be called at the start of any route
    that requires device authentication::

        auth_result = authenticate_request()
        if auth_result:
            return auth_result  # short-circuit with 401

    Returns:
        tuple[flask.Response, int] | None: A ``(JSON response, 401)`` tuple when
        authentication fails; ``None`` when the request is authenticated.
    """
    serial_number = kit_serial_from_request()
    api_key = request.headers.get("X-API-Key")
    if not serial_number or not api_key:
        return jsonify({"error": "Missing serial_number or X-API-Key"}), 401
    if not auth_service.authenticate(serial_number, api_key):
        return jsonify({"error": "Invalid serial_number or API key"}), 401
    return None
