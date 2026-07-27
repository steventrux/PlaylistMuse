from fastapi.testclient import TestClient

from backend.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "application": "PlaylistMuse"}
