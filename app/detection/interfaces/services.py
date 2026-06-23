"""Interface (REST API) layer for the Detection bounded context.

Exposes the Flask Blueprint (``detection_api``). The kit posts movement samples
to ``data-records``; each sample feeds the in-memory incremental detector (and a
transient window) — detected repetitions are enqueued and forwarded to the backend
by the background runtime. The GET endpoints are a lightweight live/debug view over
the in-memory window. The batch ``series/start|end`` lifecycle was removed.
"""
import json
import queue
from typing import Optional

from flask import Blueprint, Response, request, jsonify

from app.iam.interfaces.services import (
    authenticate_request,
    authenticate_request_query,
    kit_serial_from_request,
)
from app.detection.composition import debug_service, ingest_service, progress_broker, state

detection_api = Blueprint("detection_api", __name__)

# SSE keep-alive: an idle stream emits a comment frame this often so the socket
# stays open and the client can detect a half-open connection.
HEARTBEAT_SECONDS = 15


def is_pairing_token_valid(expected: Optional[str], provided: Optional[str]) -> bool:
    """Pure check: a provided pairing token is valid only if it matches a known expected one.

    A missing expected token (no active session for the kit) or a missing/mismatched provided
    token both fail, so an unbound stream can never be subscribed to.
    """
    return bool(expected) and bool(provided) and provided == expected


def _extract_pairing_token() -> Optional[str]:
    """Read the pairing token from ``Authorization: Bearer <token>`` (or a ``pairing_token`` query)."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):].strip()
    return request.args.get("pairing_token")


@detection_api.route("/api/v1/movement-monitoring/data-records", methods=["POST"])
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

    # Enriched batch contract (firmware): {serial_number, samples:[{target_angle, proximal_signal?}]}.
    if "samples" in data:
        samples = data["samples"]
        if not isinstance(samples, list) or not samples:
            return jsonify({"error": "samples must be a non-empty array"}), 400
        try:
            built = ingest_service.ingest_batch(serial_number, samples)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"serial_number": serial_number, "accepted": len(built)}), 201

    # Legacy single-sample contract: {serial_number|device_id, angle, created_at?}.
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


@detection_api.route("/api/v1/movement-monitoring/data-records", methods=["GET"])
def list_movement_records():
    """Return recent buffered samples for a kit (live/debug view over the window).

    Query params: ``serial_number`` (or legacy ``device_id``) *(required)*, ``limit``.
    """
    serial_number = request.args.get("serial_number") or request.args.get("device_id")
    if not serial_number:
        return jsonify({"error": "Missing serial_number query parameter"}), 400
    limit = request.args.get("limit", default=100, type=int)
    return jsonify(debug_service.recent_samples(serial_number, limit)), 200


@detection_api.route("/api/v1/movement-monitoring/analysis", methods=["GET"])
def analyze_movement():
    """Return a lightweight summary over the kit's in-memory window (debug).

    Query params: ``serial_number`` (or legacy ``device_id``) *(required)*.
    """
    serial_number = request.args.get("serial_number") or request.args.get("device_id")
    if not serial_number:
        return jsonify({"error": "Missing serial_number query parameter"}), 400
    return jsonify(debug_service.window_summary(serial_number)), 200


@detection_api.route("/api/v1/movement-monitoring/active-context", methods=["GET"])
def get_active_context():
    """Return the kit's active serie context (firmware down-channel).

    Auth: ``X-API-Key`` + ``serial_number`` query param. Returns
    ``{serial_number, active_joint, max_safe_angle, serie_id}`` (nulls when no
    serie is active). The firmware maps ``active_joint`` to an IMU pair, applies
    ``max_safe_angle`` for local safety, and re-zeros on a new ``serie_id``.
    """
    auth_result = authenticate_request_query()
    if auth_result:
        return auth_result
    serial_number = request.args.get("serial_number") or request.args.get("device_id")
    return jsonify(debug_service.active_context(serial_number)), 200


@detection_api.route("/api/v1/movement-monitoring/progress-stream", methods=["GET"])
def stream_progress():
    """Server-Sent Events stream of live repetition progress for a kit.

    The mobile app subscribes for instant rep-count feedback and reconciles against
    the backend's authoritative ``/progress`` poll, so this stream is best-effort
    and optimistic. Each ``rep`` event carries the edge-local absolute tally for the
    active serie.

    Query params: ``serial_number`` (or legacy ``device_id``) *(required)*.
    Auth: the mobile presents the session pairing token via ``Authorization: Bearer <token>``
    (or a ``pairing_token`` query param). The token is minted by the backend per active session,
    rides on the active-by-device poll into the edge's state, and is compared here before
    subscribing. There may be a brief window (≤ one poll cycle) right after a session starts where
    the edge has not cached the token yet → 401; the mobile's retry/backoff absorbs it.
    The LAN transport itself is still cleartext (TLS is a separate follow-on, §13.0.b).
    """
    serial_number = request.args.get("serial_number") or request.args.get("device_id")
    if not serial_number:
        return jsonify({"error": "Missing serial_number query parameter"}), 400

    if not is_pairing_token_valid(state.get_pairing_token(serial_number), _extract_pairing_token()):
        return jsonify({"error": "Invalid or missing pairing token"}), 401

    def event_stream():
        q = progress_broker.subscribe(serial_number)
        try:
            yield ": connected\n\n"  # prime the stream so the client's onOpen fires
            while True:
                try:
                    event = q.get(timeout=HEARTBEAT_SECONDS)
                    yield f"event: rep\ndata: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield ": heartbeat\n\n"
        finally:
            progress_broker.unsubscribe(serial_number, q)

    response = Response(event_stream(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response
