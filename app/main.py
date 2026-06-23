"""Flask application entry point for the uFlex Edge Gateway.

Wires the Flask app, registers the IAM and Detection Blueprints, initializes the
database, and starts the background runtime (correlation poller + forwarding
worker) once, before the first request.
"""

from flask import Flask

from app.detection.interfaces.services import detection_api
from app.iam.interfaces.services import iam_api
from app.shared.interfaces.docs import docs_api
from app.shared.infrastructure.database import init_db
from app.detection.composition import start_background
from app.iam.application.services import AuthApplicationService

app = Flask(__name__)
app.register_blueprint(iam_api)
app.register_blueprint(detection_api)
app.register_blueprint(docs_api)

first_request = True


@app.before_request
def setup():
    """One-time setup on the first request: init DB, seed the test kit, start workers.

    Side effects (run once per process):
        - Creates the ``devices`` and ``outbox`` tables if absent.
        - Seeds the development test kit (``uflex-kit-001``).
        - Starts the correlation poller and forwarding worker background threads.
    """
    global first_request
    if first_request:
        first_request = False
        init_db()
        AuthApplicationService().get_or_create_test_device()
        start_background()


@app.route("/status", methods=["GET"])
def status():
    """Health-check endpoint."""
    return {"status": "ok", "service": "uflex-edge-gateway"}, 200


if __name__ == "__main__":
    # host="0.0.0.0" => escucha en TODAS las interfaces de red (no solo
    # localhost), para que el ESP32 pueda alcanzar la laptop por su IP de LAN.
    # threaded=True => atiende la respuesta SSE de larga duración sin bloquear los
    # POST de ingesta del kit (el dev server es single-thread por defecto).
    app.run(host="0.0.0.0", port=5050, debug=True, threaded=True)
