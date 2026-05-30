"""Flask application entry point for the uFlex Edge Gateway.

This module wires together the Flask application, registers the IAM and
Monitoring bounded-context Blueprints, and ensures the SQLite database is
initialized (tables created, test kit seeded) exactly once before the first
HTTP request is handled.

Typical usage::

    flask --app app run
    # or
    python app.py
"""

from flask import Flask

import iam.application.services
from monitoring.interfaces.services import monitoring_api
from iam.interfaces.services import iam_api
from shared.infrastructure.database import init_db

app = Flask(__name__)
app.register_blueprint(iam_api)
app.register_blueprint(monitoring_api)

first_request = True

@app.before_request
def setup():
    """Initialize the database and seed a test kit on the very first request.

    Uses a module-level flag (``first_request``) to ensure this one-time setup
    runs only once for the lifetime of the process.  Subsequent requests bypass
    this function entirely.

    Side effects:
        - Creates the SQLite database file (``uflex_edge.db``) if absent.
        - Creates ``devices`` and ``movement_records`` tables when they do not
          exist yet (``safe=True``).
        - Inserts the default test kit (``uflex-kit-001``) if it has not
          been created previously.
    """
    global first_request
    if first_request:
        first_request = False
        init_db()
        auth_application_service = iam.application.services.AuthApplicationService()
        auth_application_service.get_or_create_test_device()

if __name__ == "__main__":
    app.run(debug=True)
