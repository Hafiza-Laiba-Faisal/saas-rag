import os

from fastapi.testclient import TestClient

from rbs_rag.web.server import app


def test_admin_login_returns_access_token(monkeypatch):
    monkeypatch.setenv("RAG_ADMIN_JWT_SECRET", "test-secret")
    monkeypatch.setenv("RAG_ADMIN_PASSWORD", "test-pass")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/admin/login",
            json={"username": "admin", "password": "test-pass"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["access_token"]
    assert payload["token"] == payload["access_token"]
