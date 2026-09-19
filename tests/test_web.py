from fastapi.testclient import TestClient

from cinegate.web.app import create_app


def test_health_endpoint() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
