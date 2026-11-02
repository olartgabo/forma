import pytest
from fastapi.testclient import TestClient

from forma_api import model_gateway
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


def _no_provider_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("provider must not be constructed or called")

    monkeypatch.setattr(model_gateway, "MetaHTTP", forbidden)
    monkeypatch.setattr(
        model_gateway.MetaGateway, "from_env", classmethod(lambda cls: forbidden())
    )


@pytest.mark.parametrize("value", [None, "", "   "])
def test_provider_status_not_configured(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("MODEL_API_KEY", raising=False)
    else:
        monkeypatch.setenv("MODEL_API_KEY", value)
    monkeypatch.delenv("META_SPARK_MODEL", raising=False)
    monkeypatch.delenv("META_SAM_MODEL", raising=False)
    _no_provider_network(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/provider/status")

    assert response.status_code == 200
    assert response.json() == {"configured": False, "model": "muse-spark-1.3"}
    assert set(response.json()) == {"configured", "model"}


def test_provider_status_configured_never_leaks_key(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "SECRET_KEY_MARKER")
    monkeypatch.delenv("META_SPARK_MODEL", raising=False)
    monkeypatch.delenv("META_SAM_MODEL", raising=False)
    _no_provider_network(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/provider/status")

    assert response.status_code == 200
    assert response.json() == {"configured": True, "model": "muse-spark-1.3"}
    assert set(response.json()) == {"configured", "model"}
    assert "SECRET_KEY_MARKER" not in response.text


def test_provider_status_custom_model(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "SECRET_KEY_MARKER")
    monkeypatch.setenv("META_SPARK_MODEL", "custom-model-1.2")
    monkeypatch.delenv("META_SAM_MODEL", raising=False)
    _no_provider_network(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/provider/status")

    assert response.json() == {"configured": True, "model": "custom-model-1.2"}
    assert "SECRET_KEY_MARKER" not in response.text


@pytest.mark.parametrize(
    "value", ["INVALID MODEL", "Bad_Model", "", "x" * 81, "model/with/slash"]
)
def test_provider_status_invalid_model_falls_back(monkeypatch, value):
    monkeypatch.setenv("MODEL_API_KEY", "SECRET_KEY_MARKER")
    monkeypatch.setenv("META_SPARK_MODEL", value)
    monkeypatch.delenv("META_SAM_MODEL", raising=False)
    _no_provider_network(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/provider/status")

    assert response.status_code == 200
    assert response.json() == {"configured": False, "model": "muse-spark-1.3"}
    assert set(response.json()) == {"configured", "model"}
    assert "SECRET_KEY_MARKER" not in response.text
    if value:
        assert value not in response.text


@pytest.mark.parametrize(
    "value", ["INVALID MODEL", "Bad_Model", "", "x" * 81, "model/with/slash"]
)
def test_provider_status_invalid_sam_model_not_configured(monkeypatch, value):
    monkeypatch.setenv("MODEL_API_KEY", "SECRET_KEY_MARKER")
    monkeypatch.delenv("META_SPARK_MODEL", raising=False)
    monkeypatch.setenv("META_SAM_MODEL", value)
    _no_provider_network(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/provider/status")

    assert response.status_code == 200
    assert response.json() == {"configured": False, "model": "muse-spark-1.3"}
    assert set(response.json()) == {"configured", "model"}
    assert "SECRET_KEY_MARKER" not in response.text
    if value:
        assert value not in response.text


@pytest.mark.parametrize("case", ["blank_key", "bad_spark", "bad_sam", "all_good"])
def test_provider_status_agrees_with_from_env(monkeypatch, case):
    def forbidden_post(*args, **kwargs):
        raise AssertionError("provider network must not be called")

    monkeypatch.setattr(model_gateway.MetaHTTP, "post", forbidden_post)
    monkeypatch.setenv("MODEL_API_KEY", "SECRET_KEY_MARKER")
    monkeypatch.delenv("META_SPARK_MODEL", raising=False)
    monkeypatch.delenv("META_SAM_MODEL", raising=False)
    if case == "blank_key":
        monkeypatch.setenv("MODEL_API_KEY", "   ")
    elif case == "bad_spark":
        monkeypatch.setenv("META_SPARK_MODEL", "INVALID MODEL")
    elif case == "bad_sam":
        monkeypatch.setenv("META_SAM_MODEL", "Bad_Model")
    elif case == "all_good":
        monkeypatch.setenv("META_SPARK_MODEL", "custom-model-1.2")
        monkeypatch.setenv("META_SAM_MODEL", "custom-sam-1.0")
    with TestClient(app) as client:
        response = client.get("/api/provider/status")

    try:
        model_gateway.MetaGateway.from_env()
    except Exception:
        constructs = False
    else:
        constructs = True

    assert response.status_code == 200
    assert response.json()["configured"] is constructs
    assert response.json()["configured"] is (case == "all_good")
    assert set(response.json()) == {"configured", "model"}
    assert "SECRET_KEY_MARKER" not in response.text
    assert "INVALID MODEL" not in response.text
    assert "Bad_Model" not in response.text
    if case == "all_good":
        assert response.json()["model"] == "custom-model-1.2"
    else:
        assert response.json()["model"] == "muse-spark-1.3"


def test_provider_status_has_a_typed_openapi_response():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    response = schema["paths"]["/api/provider/status"]["get"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ProviderStatusResponse"
    }
