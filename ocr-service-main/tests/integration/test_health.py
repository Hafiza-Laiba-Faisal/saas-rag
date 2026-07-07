"""Integration tests for /health and /version."""


def test_health_returns_200(test_client):
    response = test_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "ocr_engine_ready" in data


def test_version_returns_200(test_client):
    response = test_client.get("/version")
    assert response.status_code == 200
    data = response.json()
    assert "service_version" in data
    assert "python_version" in data
    assert "paddleocr_version" in data
