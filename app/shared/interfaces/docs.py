"""Interactive API documentation for the uFlex Edge Gateway.

Serves an OpenAPI 3.1 document and a **Scalar** API reference UI — the same
documentation experience used by the uFlex REST API backend — so the edge
contract can be browsed and captured without any extra Python dependency
(Scalar is loaded from a CDN at render time).

Routes:
    - ``GET /openapi.json``: the machine-readable OpenAPI document.
    - ``GET /scalar``: the human-readable Scalar reference UI.
"""
from flask import Blueprint, jsonify

docs_api = Blueprint("docs_api", __name__)


# --- OpenAPI document describing every endpoint the gateway exposes ---------

OPENAPI_SPEC = {
    "openapi": "3.1.0",
    "info": {
        "title": "uFlex Edge Gateway API",
        "version": "1.0.0",
        "description": (
            "Local edge gateway for the uFlex tele-rehabilitation system. It "
            "authenticates one paired IoT kit, ingests calibrated movement "
            "telemetry, detects repetitions and compensatory movements, exposes "
            "diagnostic summaries, and streams optimistic progress to the "
            "patient mobile application."
        ),
    },
    "servers": [{"url": "/", "description": "This gateway"}],
    "tags": [
        {"name": "Health"},
        {"name": "Ingestion",
         "description": "Authenticated movement telemetry received from the IoT kit."},
        {"name": "Diagnostics",
         "description": "Read-only live views over the transient movement window."},
        {"name": "Firmware context",
         "description": "Active exercise context consumed by the kit firmware."},
        {"name": "Mobile progress",
         "description": "Best-effort Server-Sent Events used by the patient application."},
    ],
    "components": {
        "securitySchemes": {
            "ApiKeyAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
                "description": "API key provisioned for the paired IoT kit.",
            },
            "PairingTokenAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "opaque pairing token",
                "description": "Session-scoped token returned to the patient mobile application.",
            },
        },
        "schemas": {
            "SingleMovementReading": {
                "type": "object",
                "required": ["serial_number", "angle"],
                "properties": {
                    "serial_number": {
                        "type": "string",
                        "description": "Cross-service kit identity.",
                        "example": "uflex-kit-001",
                    },
                    "angle": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 360,
                        "example": 72.5,
                    },
                    "created_at": {"type": "string", "format": "date-time",
                                   "example": "2026-08-11T12:00:00-05:00"},
                },
            },
            "MovementSample": {
                "type": "object",
                "required": ["target_angle"],
                "properties": {
                    "target_angle": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 360,
                        "description": "Calibrated angle of the joint being treated.",
                        "example": 72.0,
                    },
                    "proximal_signal": {
                        "type": ["number", "null"],
                        "description": "Optional proximal-segment signal used for compensation detection.",
                        "example": 2.3,
                    },
                    "recorded_at": {
                        "type": ["string", "null"],
                        "format": "date-time",
                        "description": "Optional timestamp; the edge stamps the sample when omitted.",
                    },
                },
            },
            "MovementBatch": {
                "type": "object",
                "required": ["serial_number", "samples"],
                "properties": {
                    "serial_number": {"type": "string", "example": "uflex-kit-001"},
                    "samples": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"$ref": "#/components/schemas/MovementSample"},
                    },
                },
            },
            "AcceptedReading": {
                "type": "object",
                "required": ["serial_number", "angle", "recorded_at"],
                "properties": {
                    "serial_number": {"type": "string", "example": "uflex-kit-001"},
                    "angle": {"type": "number", "example": 72.5},
                    "recorded_at": {"type": "string", "format": "date-time"},
                },
            },
            "AcceptedBatch": {
                "type": "object",
                "required": ["serial_number", "accepted"],
                "properties": {
                    "serial_number": {"type": "string", "example": "uflex-kit-001"},
                    "accepted": {"type": "integer", "example": 3},
                },
            },
            "MovementRecord": {
                "type": "object",
                "properties": {
                    "serial_number": {"type": "string", "example": "uflex-kit-001"},
                    "angle": {"type": "number", "example": 72.5},
                    "recorded_at": {"type": "string", "format": "date-time"},
                },
            },
            "MovementAnalysis": {
                "type": "object",
                "properties": {
                    "serial_number": {"type": "string", "example": "uflex-kit-001"},
                    "sample_count": {"type": "integer", "example": 11},
                    "min_angle": {"type": ["number", "null"], "example": 0.0},
                    "max_angle": {"type": ["number", "null"], "example": 88.0},
                    "range_of_motion": {"type": ["number", "null"], "example": 88.0},
                    "mean_angle": {"type": ["number", "null"], "example": 40.55},
                    "active_serie_id": {"type": ["string", "null"], "example": "serie-abc"},
                },
            },
            "ActiveContext": {
                "type": "object",
                "properties": {
                    "serial_number": {"type": "string", "example": "uflex-kit-001"},
                    "active_joint": {
                        "type": ["string", "null"],
                        "enum": ["ELBOW", "WRIST", None],
                        "example": "ELBOW",
                    },
                    "active_movement": {
                        "type": ["string", "null"],
                        "enum": ["FLEXION", "EXTENSION", "PRONATION", "SUPINATION", None],
                        "example": "FLEXION",
                    },
                    "max_safe_angle": {"type": ["number", "null"], "example": 95.0},
                    "serie_id": {"type": ["string", "null"], "example": "serie-abc"},
                },
            },
            "Error": {
                "type": "object",
                "properties": {"error": {"type": "string"}},
            },
        },
    },
    "paths": {
        "/status": {
            "get": {
                "tags": ["Health"],
                "summary": "Health check",
                "responses": {"200": {"description": "Gateway is up"}},
            }
        },
        "/api/v1/movement-monitoring/data-records": {
            "post": {
                "tags": ["Ingestion"],
                "summary": "Ingest movement telemetry",
                "description": (
                    "Accepts either one legacy-compatible calibrated reading or an ordered "
                    "firmware batch. The kit serial and X-API-Key are validated together."
                ),
                "security": [{"ApiKeyAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "oneOf": [
                                    {"$ref": "#/components/schemas/SingleMovementReading"},
                                    {"$ref": "#/components/schemas/MovementBatch"},
                                ]
                            },
                            "examples": {
                                "singleReading": {
                                    "summary": "Single calibrated reading",
                                    "value": {
                                        "serial_number": "uflex-kit-001",
                                        "angle": 72.5,
                                        "created_at": "2026-08-11T12:00:00-05:00",
                                    },
                                },
                                "movementBatch": {
                                    "summary": "Ordered flexion movement",
                                    "value": {
                                        "serial_number": "uflex-kit-001",
                                        "samples": [
                                            {"target_angle": 0.0, "proximal_signal": 2.0},
                                            {"target_angle": 45.0, "proximal_signal": 2.2},
                                            {"target_angle": 88.0, "proximal_signal": 2.4},
                                            {"target_angle": 45.0, "proximal_signal": 2.1},
                                            {"target_angle": 0.0, "proximal_signal": 2.0},
                                        ],
                                    },
                                },
                            },
                        }
                    },
                },
                "responses": {
                    "201": {
                        "description": "Reading or batch accepted",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "oneOf": [
                                        {"$ref": "#/components/schemas/AcceptedReading"},
                                        {"$ref": "#/components/schemas/AcceptedBatch"},
                                    ]
                                }
                            }
                        },
                    },
                    "400": {
                        "description": "Missing field or invalid value",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
                    },
                    "401": {
                        "description": "Missing or invalid kit credentials",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}},
                    },
                },
            },
            "get": {
                "tags": ["Diagnostics"],
                "summary": "List recent movement readings",
                "parameters": [
                    {
                        "name": "serial_number",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                        "example": "uflex-kit-001",
                    },
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 100}},
                ],
                "responses": {
                    "200": {
                        "description": "Recent readings ordered by ingestion",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/MovementRecord"},
                                }
                            }
                        },
                    },
                    "400": {"description": "Missing serial_number"},
                },
            },
        },
        "/api/v1/movement-monitoring/analysis": {
            "get": {
                "tags": ["Diagnostics"],
                "summary": "Summarize the live movement window",
                "parameters": [
                    {
                        "name": "serial_number",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                        "example": "uflex-kit-001",
                    },
                ],
                "responses": {
                    "200": {
                        "description": "Range-of-motion summary over the transient window",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/MovementAnalysis"}}},
                    },
                    "400": {"description": "Missing serial_number"},
                },
            }
        },
        "/api/v1/movement-monitoring/active-context": {
            "get": {
                "tags": ["Firmware context"],
                "summary": "Get the active exercise context",
                "description": (
                    "Returns the joint, movement, safe-angle limit and serie currently "
                    "correlated from the central backend for this kit."
                ),
                "security": [{"ApiKeyAuth": []}],
                "parameters": [
                    {
                        "name": "serial_number",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                        "example": "uflex-kit-001",
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Current context; nullable fields mean no active serie",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ActiveContext"}}},
                    },
                    "401": {"description": "Missing or invalid kit credentials"},
                },
            }
        },
        "/api/v1/movement-monitoring/progress-stream": {
            "get": {
                "tags": ["Mobile progress"],
                "summary": "Stream live repetition progress",
                "description": (
                    "Opens a Server-Sent Events stream. Prefer the bearer pairing token; "
                    "the pairing_token query parameter is retained as a debug fallback."
                ),
                "security": [{"PairingTokenAuth": []}],
                "parameters": [
                    {
                        "name": "serial_number",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string"},
                        "example": "uflex-kit-001",
                    },
                    {
                        "name": "pairing_token",
                        "in": "query",
                        "required": False,
                        "deprecated": True,
                        "schema": {"type": "string"},
                        "description": "Debug fallback when the Authorization header cannot be set.",
                    },
                ],
                "responses": {
                    "200": {
                        "description": "SSE stream of rep events and heartbeat comments",
                        "content": {
                            "text/event-stream": {
                                "schema": {"type": "string"},
                                "example": (
                                    "event: rep\n"
                                    "data: {\"serie_id\":\"serie-abc\",\"reps_detected\":1,"
                                    "\"classification\":\"good\",\"recorded_at\":"
                                    "\"2026-08-11T17:00:00+00:00\"}\n\n"
                                ),
                            }
                        },
                    },
                    "400": {"description": "Missing serial_number"},
                    "401": {"description": "Missing or invalid pairing token"},
                },
            }
        },
    },
}


_SCALAR_HTML = """<!doctype html>
<html>
  <head>
    <title>uFlex Edge Gateway API</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
    <script id="api-reference" data-url="/openapi.json"></script>
    <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
  </body>
</html>
"""


@docs_api.route("/openapi.json", methods=["GET"])
def openapi_document():
    """Return the OpenAPI 3.1 document describing the gateway's endpoints."""
    return jsonify(OPENAPI_SPEC)


@docs_api.route("/scalar", methods=["GET"])
def scalar_reference():
    """Render the Scalar API reference UI (loads the spec from ``/openapi.json``)."""
    return _SCALAR_HTML
