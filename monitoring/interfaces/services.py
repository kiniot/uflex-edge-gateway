"""Interface (REST API) layer for the Monitoring bounded context.

Exposes a Flask Blueprint (``monitoring_api``) that translates incoming HTTP
requests into calls to the application service and maps the results back to
JSON responses.  This layer owns no domain logic; it is responsible solely
for I/O concerns: parsing request data, authentication delegation, and HTTP
status code selection.
"""
from flask import Blueprint, request, jsonify

from monitoring.application.services import (
    MovementRecordApplicationService,
    MovementAnalysisApplicationService,
    SerieExecutionApplicationService,
)
from iam.interfaces.services import authenticate_request

monitoring_api = Blueprint("monitoring_api", __name__)

# Module-level singletons; safe because Flask handles one request at a time
# within a single worker (no shared mutable state on these objects).
movement_record_service = MovementRecordApplicationService()
movement_analysis_service = MovementAnalysisApplicationService()
serie_execution_service = SerieExecutionApplicationService()


def _serie_execution_to_dict(execution):
    """Serialise a :class:`SerieExecution` aggregate to a JSON-ready dict."""
    return {
        "id": execution.id,
        "serie_id": execution.serie_id,
        "device_id": execution.device_id,
        "status": execution.status,
        "target_rom": execution.target_rom,
        "target_reps": execution.target_reps,
        "movement_type": execution.movement_type,
        "body_part": execution.body_part,
        "max_safe_angle": execution.max_safe_angle,
        "reps_done": execution.reps_done,
        "good_reps": execution.good_reps,
        "bad_reps_incomplete": execution.bad_reps_incomplete,
        "bad_reps_unsafe": execution.bad_reps_unsafe,
        "avg_rom": execution.avg_rom,
        "min_angle": execution.min_angle,
        "max_angle": execution.max_angle,
        "valoracion": execution.valoracion,
        "dangerous_movement_detected": execution.dangerous_movement_detected,
        "started_at": execution.started_at.isoformat()
        if hasattr(execution.started_at, "isoformat") else execution.started_at,
        "ended_at": execution.ended_at.isoformat()
        if (execution.ended_at and hasattr(execution.ended_at, "isoformat")) else execution.ended_at,
    }


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


@monitoring_api.route("/api/v1/movement-monitoring/data-records", methods=["GET"])
def list_movement_records():
    """List recent raw movement readings (live view / debugging).

    **Query parameters:**

    - ``device_id`` *(str, optional)*: Restrict results to a single kit.
    - ``limit`` *(int, optional)*: Maximum readings to return (default 100).

    **Responses:**

    - ``200 OK`` – JSON array of readings (newest first when unfiltered,
      chronological when filtered by kit).

    Returns:
        tuple[flask.Response, int]: The readings as JSON with HTTP 200.
    """
    device_id = request.args.get("device_id")
    limit = request.args.get("limit", default=100, type=int)
    records = movement_analysis_service.get_recent_records(device_id, limit)
    return jsonify([
        {
            "id": record.id,
            "device_id": record.device_id,
            "angle": record.angle,
            "created_at": record.created_at.isoformat(),
        }
        for record in records
    ]), 200


@monitoring_api.route("/api/v1/movement-monitoring/analysis", methods=["GET"])
def analyze_movement():
    """Return the digested movement summary for a kit (the edge's processing output).

    Aggregates recent readings into clinical metrics — range of motion,
    repetitions, min/max, mean and peak angular velocity — and, when
    thresholds are supplied, evaluates them to decide the actuator action.

    **Query parameters:**

    - ``device_id`` *(str, required)*: The kit to analyse.
    - ``limit`` *(int, optional)*: Recent readings to analyse (default 200).
    - ``target_rom`` *(float, optional)*: Backend range-of-motion goal in degrees.
    - ``max_safe_angle`` *(float, optional)*: Backend safety ceiling in degrees.

    **Responses:**

    - ``200 OK`` – JSON summary of the derived metrics.
    - ``400 Bad Request`` – ``device_id`` query parameter is missing.

    Returns:
        tuple[flask.Response, int]: The summary as JSON with the HTTP status.
    """
    device_id = request.args.get("device_id")
    if not device_id:
        return jsonify({"error": "Missing device_id query parameter"}), 400
    limit = request.args.get("limit", default=200, type=int)
    target_rom = request.args.get("target_rom", type=float)
    max_safe_angle = request.args.get("max_safe_angle", type=float)
    summary = movement_analysis_service.analyze_device(
        device_id, limit, target_rom, max_safe_angle
    )
    return jsonify(summary), 200


@monitoring_api.route("/api/v1/movement-monitoring/series/start", methods=["POST"])
def start_serie():
    """Open the execution of a therapy series.

    Clears any stale buffer/open execution for the kit and records the target
    parameters of the series about to be performed.  Raw readings posted to
    ``data-records`` after this call belong to this series until it is ended.

    **Headers:** ``X-API-Key`` *(required)*, ``Content-Type: application/json``.

    **Request body (JSON):**

    - ``device_id`` *(str, required)*.
    - ``serie_id`` *(str, optional)*: reference to the series definition.
    - ``target_rom`` *(float, optional)*, ``target_reps`` *(int, optional)*.
    - ``movement_type`` *(str, optional)*, ``body_part`` *(str, optional)*.
    - ``max_safe_angle`` *(float, optional)*.

    **Responses:** ``201`` with the opened execution; ``400`` missing fields;
    ``401`` bad credentials.
    """
    auth_result = authenticate_request()
    if auth_result:
        return auth_result

    data = request.json or {}
    try:
        execution = serie_execution_service.start_serie(
            device_id=data["device_id"],
            api_key=request.headers.get("X-API-Key"),
            serie_id=data.get("serie_id"),
            target_rom=data.get("target_rom"),
            target_reps=data.get("target_reps"),
            movement_type=data.get("movement_type"),
            body_part=data.get("body_part"),
            max_safe_angle=data.get("max_safe_angle"),
        )
        return jsonify(_serie_execution_to_dict(execution)), 201
    except KeyError:
        return jsonify({"error": "Missing required fields"}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@monitoring_api.route("/api/v1/movement-monitoring/series/end", methods=["POST"])
def end_serie():
    """Close the open series for a kit and return its chewed result.

    Classifies each repetition (good / incomplete / unsafe), aggregates the
    outcome (counts, average achieved ROM, ``valoracion``, danger flag), persists
    it and purges the raw buffer.

    **Headers:** ``X-API-Key`` *(required)*, ``Content-Type: application/json``.

    **Request body (JSON):** ``device_id`` *(str, required)*.

    **Responses:** ``200`` with the closed execution and a ``repetitions``
    breakdown; ``400`` missing fields or no open series; ``401`` bad credentials.
    """
    auth_result = authenticate_request()
    if auth_result:
        return auth_result

    data = request.json or {}
    try:
        execution, repetitions = serie_execution_service.end_serie(
            device_id=data["device_id"],
            api_key=request.headers.get("X-API-Key"),
        )
        result = _serie_execution_to_dict(execution)
        result["repetitions"] = repetitions
        return jsonify(result), 200
    except KeyError:
        return jsonify({"error": "Missing required fields"}), 400
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@monitoring_api.route("/api/v1/movement-monitoring/series/<int:execution_id>/result", methods=["GET"])
def get_serie_result(execution_id):
    """Return a stored series execution result by id.

    **Responses:** ``200`` with the execution; ``404`` when it does not exist.
    """
    execution = serie_execution_service.get_result(execution_id)
    if not execution:
        return jsonify({"error": "Series execution not found"}), 404
    return jsonify(_serie_execution_to_dict(execution)), 200
