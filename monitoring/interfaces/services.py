"""Interface (REST API) layer for the Monitoring bounded context.

Exposes a Flask Blueprint (``monitoring_api``) that translates incoming HTTP
requests into calls to the application service and maps the results back to
JSON responses.  This layer owns no domain logic; it is responsible solely
for I/O concerns: parsing request data, authentication delegation, and HTTP
status code selection.
"""
from flask import Blueprint, request, jsonify

from monitoring.application.services import MovementRecordApplicationService
from iam.interfaces.services import authenticate_request

monitoring_api = Blueprint("monitoring_api", __name__)

# Module-level singleton; safe because Flask handles one request at a time
# within a single worker (no shared mutable state on this object).
movement_record_service = MovementRecordApplicationService()


@monitoring_api.route("/api/v1/movement-monitoring/data-records", methods=["POST"])
def create_movement_record():
    """Create a new movement-monitoring data record.

    Validates the kit identity via the ``X-API-Key`` header and the
    ``device_id`` field in the request body before delegating to the
    application service to apply domain rules and persist the record.

    **Request headers:**

    - ``X-API-Key`` *(required)*: API key paired with the kit.
    - ``Content-Type: application/json`` *(required)*.

    **Request body (JSON):**

    .. code-block:: json

        {
            "device_id": "uflex-kit-001",
            "angle": 92.5,
            "created_at": "2026-05-29T18:23:00-05:00"
        }

    - ``device_id`` *(str, required)*: Identifier of the submitting kit.
    - ``angle`` *(float, required)*: Joint flexion angle in degrees.
    - ``created_at`` *(str, optional)*: ISO 8601 timestamp; defaults to the
      current UTC time when omitted.

    **Responses:**

    - ``201 Created`` – Record saved successfully.  Body contains the
      persisted record with its assigned ``id`` and a UTC ``created_at``.
    - ``400 Bad Request`` – A required field is missing or a value is
      invalid (e.g. angle out of range, malformed timestamp).
    - ``401 Unauthorized`` – ``device_id`` or ``X-API-Key`` is absent or
      does not match a registered kit.

    Returns:
        tuple[flask.Response, int]: A JSON response body paired with the
        appropriate HTTP status code.
    """
    auth_result = authenticate_request()
    if auth_result:
        return auth_result

    data = request.json
    try:
        device_id = data["device_id"]
        angle = data["angle"]
        created_at = data.get("created_at")
        record = movement_record_service.create_movement_record(
            device_id, angle, created_at, request.headers.get("X-API-Key")
        )
        return jsonify({
            "id": record.id,
            "device_id": record.device_id,
            "angle": record.angle,
            "created_at": record.created_at.isoformat() + "Z"
        }), 201
    except KeyError:
        return jsonify({"error": "Missing required fields"}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
