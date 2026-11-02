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


@pytest.fixture(autouse=True)
def default_sam_model(monkeypatch):
    monkeypatch.delenv("META_SAM_MODEL", raising=False)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_provider_status_not_configured(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("MODEL_API_KEY", raising=False)
    else:
        monkeypatch.setenv("MODEL_API_KEY", value)
    monkeypatch.delenv("META_SPARK_MODEL", raising=False)
    _no_provider_network(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/provider/status")

    assert response.status_code == 200
    assert response.json() == {"configured": False, "model": "muse-spark-1.3"}
    assert set(response.json()) == {"configured", "model"}


def test_provider_status_configured_never_leaks_key(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "SECRET_KEY_MARKER")
    monkeypatch.delenv("META_SPARK_MODEL", raising=False)
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
    _no_provider_network(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/provider/status")

    assert response.json() == {"configured": True, "model": "custom-model-1.2"}
    assert "SECRET_KEY_MARKER" not in response.text


@pytest.mark.parametrize(
    "value", ["INVALID MODEL", "Bad_Model", "", "x" * 81, "model/with/slash"]
)
def test_provider_status_invalid_spark_is_not_configured(monkeypatch, value):
    monkeypatch.setenv("MODEL_API_KEY", "SECRET_KEY_MARKER")
    monkeypatch.setenv("META_SPARK_MODEL", value)
    _no_provider_network(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/provider/status")

    assert response.json() == {"configured": False, "model": "muse-spark-1.3"}
    assert "SECRET_KEY_MARKER" not in response.text
    if value:
        assert value not in response.text


@pytest.mark.parametrize(
    "value", ["INVALID MODEL", "Bad_Model", "", "x" * 81, "model/with/slash"]
)
def test_provider_status_invalid_sam_is_not_configured(monkeypatch, value):
    monkeypatch.setenv("MODEL_API_KEY", "SECRET_KEY_MARKER")
    monkeypatch.setenv("META_SPARK_MODEL", "custom-spark-1.2")
    monkeypatch.setenv("META_SAM_MODEL", value)
    _no_provider_network(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/provider/status")

    assert response.json() == {"configured": False, "model": "custom-spark-1.2"}
    assert "SECRET_KEY_MARKER" not in response.text
    if value:
        assert value not in response.text


@pytest.mark.parametrize("key", [None, "", " \t", "SYNTHETIC_KEY"])
@pytest.mark.parametrize(
    ("spark", "sam"),
    [
        (None, None),
        ("custom-spark-1.2", "custom-sam-2.0"),
        ("Bad_Model", None),
        (None, "Bad_Model"),
        ("", None),
        (None, ""),
    ],
)
def test_provider_status_agrees_with_real_gateway_configuration(
    monkeypatch, key, spark, sam
):
    def forbidden(*args, **kwargs):
        raise AssertionError("configuration checks must not make HTTP requests")

    monkeypatch.setattr(model_gateway.MetaHTTP, "post", forbidden)
    monkeypatch.setattr(model_gateway.http.client, "HTTPSConnection", forbidden)
    for name, value in (
        ("MODEL_API_KEY", key),
        ("META_SPARK_MODEL", spark),
        ("META_SAM_MODEL", sam),
    ):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    try:
        gateway = model_gateway.MetaGateway.from_env()
    except (model_gateway.GatewayError, ValueError):
        configured = False
    else:
        configured = True
        assert isinstance(gateway.transport, model_gateway.MetaHTTP)

    with TestClient(app) as client:
        response = client.get("/api/provider/status")

    assert response.status_code == 200
    assert response.json()["configured"] is configured
    if configured:
        assert response.json()["model"] == gateway.spark


def test_provider_status_has_a_typed_openapi_response():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    response = schema["paths"]["/api/provider/status"]["get"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ProviderStatusResponse"
    }
