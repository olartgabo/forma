import asyncio

import httpx2 as httpx
from fastapi.testclient import TestClient

from forma_api.main import create_app
from forma_api.model_gateway import MetaGateway
from forma_api.provider_credentials import model_api_key


def test_byok_reaches_gateway_only_for_its_request(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "server-test-value")
    app = create_app(tmp_path, credentials={})
    seen = []

    @app.get("/test-credential")
    def inspect_credential():
        seen.append(MetaGateway.from_env().transport._key)
        return {"ok": True}

    with TestClient(app) as client:
        assert client.get(
            "/test-credential", headers={"X-Forma-Model-Key": "request-test-value"}
        ).json() == {"ok": True}
        assert client.get("/test-credential").status_code == 200
    assert seen == ["request-test-value", "server-test-value"]
    assert model_api_key() == "server-test-value"


def test_byok_status_and_validation_do_not_echo_key(tmp_path, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with TestClient(create_app(tmp_path, credentials={})) as client:
        assert not client.get("/api/provider/status").json()["configured"]
        response = client.get(
            "/api/provider/status", headers={"X-Forma-Model-Key": "request-test-value"}
        )
        assert response.json()["configured"]
        assert "request-test-value" not in response.text
        for value in ("", "has spaces", "x" * 4097):
            response = client.get(
                "/api/provider/status", headers={"X-Forma-Model-Key": value}
            )
            assert response.status_code == 400
            assert response.json() == {"detail": "Invalid model credential header"}
        response = client.get(
            "/api/provider/status",
            headers=[("X-Forma-Model-Key", "first"), ("X-Forma-Model-Key", "second")],
        )
        assert response.status_code == 400
        assert (
            client.get(
                "/api/projects", headers={"X-Forma-Model-Key": "request-test-value"}
            ).status_code
            == 401
        )


def test_concurrent_requests_and_errors_clear_context(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "server-test-value")
    app = create_app(tmp_path, credentials={})

    @app.get("/test-overlap")
    async def overlap():
        before = model_api_key()
        await asyncio.sleep(0.01)
        assert model_api_key() == before
        return {"ok": True}

    @app.get("/test-error")
    async def fail():
        raise RuntimeError("synthetic failure")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            responses = await asyncio.gather(
                client.get(
                    "/test-overlap", headers={"X-Forma-Model-Key": "first-test"}
                ),
                client.get(
                    "/test-overlap", headers={"X-Forma-Model-Key": "second-test"}
                ),
                client.get("/test-overlap"),
                client.get("/test-error", headers={"X-Forma-Model-Key": "error-test"}),
            )
        assert [r.status_code for r in responses] == [200, 200, 200, 500]

    asyncio.run(run())
    assert model_api_key() == "server-test-value"
