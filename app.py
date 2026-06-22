"""Flask application entry point for the uFlex Edge Gateway.

Wires the Flask app, registers the IAM and Monitoring Blueprints, initializes the
database, and starts the background runtime (correlation poller + forwarding
worker) once, before the first request.
"""

from flask import Flask

import iam.application.services
from monitoring.interfaces.services import monitoring_api
from iam.interfaces.services import iam_api
from shared.interfaces.docs import docs_api
from shared.infrastructure.database import init_db
from monitoring.composition import start_background

app = Flask(__name__)
app.register_blueprint(iam_api)
app.register_blueprint(monitoring_api)
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
        iam.application.services.AuthApplicationService().get_or_create_test_device()
        start_background()


@app.route("/status", methods=["GET"])
def status():
    """Health-check endpoint."""
    return {"status": "ok", "service": "uflex-edge-gateway"}, 200


if __name__ == "__main__":
    # host="0.0.0.0" => escucha en TODAS las interfaces de red (no solo
    # localhost), para que el ESP32 pueda alcanzar la laptop por su IP de LAN.
    app.run(host="0.0.0.0", port=5000, debug=True)
