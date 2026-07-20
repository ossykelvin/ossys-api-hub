from fastapi.testclient import TestClient

from app.main import app


def test_api_authentication_is_optional_locally(monkeypatch) -> None:
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    response = TestClient(app).get("/api/saved-query-groups")
    assert response.status_code == 200


def test_api_authentication_protects_data_routes(monkeypatch) -> None:
    monkeypatch.setenv("APP_USERNAME", "ossy")
    monkeypatch.setenv("APP_PASSWORD", "test-password")
    client = TestClient(app)

    assert client.get("/api/health").status_code == 200
    unauthorized = client.get("/api/saved-query-groups")
    assert unauthorized.status_code == 401
    assert unauthorized.json() == {"detail": "Sign in to Ossy's API Hub"}
    assert "www-authenticate" not in unauthorized.headers

    authorized = client.get(
        "/api/saved-query-groups",
        auth=("ossy", "test-password"),
    )
    assert authorized.status_code == 200
