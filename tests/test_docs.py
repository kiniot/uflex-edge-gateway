"""Contract checks for the OpenAPI document rendered by Scalar."""

from app.shared.interfaces.docs import OPENAPI_SPEC


def test_openapi_documents_every_current_movement_monitoring_route():
    paths = OPENAPI_SPEC["paths"]

    assert "/api/v1/movement-monitoring/data-records" in paths
    assert "/api/v1/movement-monitoring/analysis" in paths
    assert "/api/v1/movement-monitoring/active-context" in paths
    assert "/api/v1/movement-monitoring/progress-stream" in paths


def test_openapi_does_not_advertise_removed_movement_detection_routes():
    assert all("/movement-detection/" not in path for path in OPENAPI_SPEC["paths"])


def test_ingestion_contract_documents_single_and_batch_examples():
    media_type = OPENAPI_SPEC["paths"][
        "/api/v1/movement-monitoring/data-records"
    ]["post"]["requestBody"]["content"]["application/json"]

    assert set(media_type["examples"]) == {"singleReading", "movementBatch"}
    assert len(media_type["schema"]["oneOf"]) == 2
