"""Interface (REST API) layer for the Monitoring bounded context.

Exposes the Flask Blueprint (``monitoring_api``). The kit posts movement samples
to ``data-records``; each sample feeds the in-memory incremental detector (and a
transient window) — detected repetitions are enqueued and forwarded to the backend
by the background runtime. The GET endpoints are a lightweight live/debug view over
the in-memory window. The batch ``series/start|end`` lifecycle was removed.
"""
from flask import Blueprint, request, jsonify

from iam.interfaces.services import authenticate_request, kit_serial_from_request
from monitoring.composition import debug_service, ingest_service

monitoring_api = Blueprint("monitoring_api", __name__)


@monitoring_api.route("/api/v1/movement-monitoring/data-records", methods=["POST"])
def create_movement_record():
    """Ingest one movement sample from an authenticated kit.

    Validates kit identity (``X-API-Key`` + serial), then feeds the sample to the
    active detector. A repetition completed by this sample is enqueued for
    forwarding asynchronously.

    Body: ``{ "serial_number" | "device_id", "angle", "created_at"? }``.
    Responses: ``201`` accepted; ``400`` missing/invalid fields; ``401`` bad credentials.
    """
    auth_result = authenticate_request()
    if auth_result:
        return auth_result

    data = request.json or {}
    serial_number = kit_serial_from_request()
    if "angle" not in data:
        return jsonify({"error": "Missing required fields"}), 400
    try:
        sample = ingest_service.ingest(serial_number, data["angle"], data.get("created_at"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({
        "serial_number": sample.serial_number,
        "angle": sample.angle,
        "recorded_at": sample.recorded_at.isoformat(),
    }), 201


@monitoring_api.route("/api/v1/movement-monitoring/data-records", methods=["GET"])
def list_movement_records():
    """Return recent buffered samples for a kit (live/debug view over the window).

    Query params: ``serial_number`` (or legacy ``device_id``) *(required)*, ``limit``.
    """
    serial_number = request.args.get("serial_number") or request.args.get("device_id")
    if not serial_number:
        return jsonify({"error": "Missing serial_number query parameter"}), 400
    limit = request.args.get("limit", default=100, type=int)
    return jsonify(debug_service.recent_samples(serial_number, limit)), 200


@monitoring_api.route("/api/v1/movement-monitoring/analysis", methods=["GET"])
def analyze_movement():
    """Return a lightweight summary over the kit's in-memory window (debug).

    Query params: ``serial_number`` (or legacy ``device_id``) *(required)*.
    """
    serial_number = request.args.get("serial_number") or request.args.get("device_id")
    if not serial_number:
        return jsonify({"error": "Missing serial_number query parameter"}), 400
    return jsonify(debug_service.window_summary(serial_number)), 200
