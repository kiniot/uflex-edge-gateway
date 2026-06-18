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
            "Edge gateway for a tele-rehabilitation system. Ingests raw joint "
            "flexion angles from an IoT Kit, processes them into clinical "
            "metrics (range of motion, repetition quality, series results) and "
            "evaluates them against backend thresholds."
        ),
    },
    "servers": [{"url": "/", "description": "This gateway"}],
    "tags": [
        {"name": "Health"},
        {"name": "Ingestion",
         "description": "Raw real-time readings as they arrive from the IoT Kit "
                        "(the data we store)."},
        {"name": "Analysis",
         "description": "On-the-fly digested metrics for a kit (debug view)."},
        {"name": "Series execution",
         "description": "Processed series results — the chewed data the backend "
                        "(and the mobile/web app) would consume."},
    ],
    "components": {
        "securitySchemes": {
            "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
        },
        "schemas": {
            "Reading": {
                "type": "object",
                "required": ["device_id", "angle"],
                "properties": {
                    "device_id": {"type": "string", "example": "uflex-kit-001"},
                    "angle": {"type": "number", "minimum": 0, "maximum": 360, "example": 92.5},
                    "created_at": {"type": "string", "format": "date-time",
                                   "example": "2026-06-16T18:23:00-05:00"},
                },
            },
            "SeriesStart": {
                "type": "object",
                "required": ["device_id"],
                "properties": {
                    "device_id": {"type": "string", "example": "uflex-kit-001"},
                    "serie_id": {"type": "string", "example": "serie-abc"},
                    "target_rom": {"type": "number", "example": 70},
                    "target_reps": {"type": "integer", "example": 4},
                    "movement_type": {"type": "string", "example": "flexion"},
                    "body_part": {"type": "string", "example": "codo"},
                    "max_safe_angle": {"type": "number", "example": 130},
                },
            },
            "DeviceRef": {
                "type": "object",
                "required": ["device_id"],
                "properties": {"device_id": {"type": "string", "example": "uflex-kit-001"}},
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
                "summary": "Ingest one raw angle reading",
                "security": [{"ApiKeyAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Reading"}}},
                },
                "responses": {
                    "201": {"description": "Reading stored"},
                    "400": {"description": "Missing field or invalid value"},
                    "401": {"description": "Missing or invalid credentials"},
                },
            },
            "get": {
                "tags": ["Ingestion"],
                "summary": "List recent raw readings (live view / debugging)",
                "parameters": [
                    {"name": "device_id", "in": "query", "schema": {"type": "string"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 100}},
                ],
                "responses": {"200": {"description": "Array of readings"}},
            },
        },
        "/api/v1/movement-monitoring/analysis": {
            "get": {
                "tags": ["Analysis"],
                "summary": "On-the-fly digested summary + threshold/actuator decision",
                "parameters": [
                    {"name": "device_id", "in": "query", "required": True, "schema": {"type": "string"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 200}},
                    {"name": "target_rom", "in": "query", "schema": {"type": "number"}},
                    {"name": "max_safe_angle", "in": "query", "schema": {"type": "number"}},
                ],
                "responses": {
                    "200": {"description": "Digested metrics"},
                    "400": {"description": "Missing device_id"},
                },
            }
        },
        "/api/v1/movement-monitoring/series/start": {
            "post": {
                "tags": ["Series execution"],
                "summary": "Open a series execution with its target parameters",
                "security": [{"ApiKeyAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/SeriesStart"}}},
                },
                "responses": {
                    "201": {"description": "Series opened"},
                    "400": {"description": "Missing fields"},
                    "401": {"description": "Bad credentials"},
                },
            }
        },
        "/api/v1/movement-monitoring/series/end": {
            "post": {
                "tags": ["Series execution"],
                "summary": "Close the series: classify reps good/bad, store the result",
                "security": [{"ApiKeyAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/DeviceRef"}}},
                },
                "responses": {
                    "200": {"description": "Series result with per-repetition breakdown"},
                    "400": {"description": "Missing fields or no open series"},
                    "401": {"description": "Bad credentials"},
                },
            }
        },
        "/api/v1/movement-monitoring/series": {
            "get": {
                "tags": ["Series execution"],
                "summary": "List processed series results (what the backend consumes)",
                "parameters": [
                    {"name": "device_id", "in": "query", "schema": {"type": "string"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50}},
                ],
                "responses": {"200": {"description": "Array of processed series executions"}},
            }
        },
        "/api/v1/movement-monitoring/series/{execution_id}/result": {
            "get": {
                "tags": ["Series execution"],
                "summary": "Read a stored series execution result",
                "parameters": [
                    {"name": "execution_id", "in": "path", "required": True,
                     "schema": {"type": "integer"}},
                ],
                "responses": {
                    "200": {"description": "Series execution"},
                    "404": {"description": "Not found"},
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
