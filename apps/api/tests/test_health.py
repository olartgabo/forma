from fastapi.testclient import TestClient

from forma_api.main import app


def test_health_without_model_credentials(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_has_a_typed_openapi_response():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    response = schema["paths"]["/api/health"]["get"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HealthResponse"
    }
