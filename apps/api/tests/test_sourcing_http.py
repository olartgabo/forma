import json
import threading

import pytest

from forma_api.model_gateway import GatewayError
from forma_api.sourcing_http import SourcingHTTP


class Response:
    status = 200

    def __init__(self, body):
        self.body = body

    def read1(self, size):
        result, self.body = self.body[:size], self.body[size:]
        return result


class Connection:
    requests = []
    status = 200
    identity = "resp_existing"

    def __init__(self, host, timeout):
        assert host == "api.meta.ai"
        self.sock = self

    def connect(self):
        pass

    def request(self, method, path, headers):
        self.requests.append((method, path, headers))

    def getresponse(self):
        result = Response(
            json.dumps(
                {"id": self.identity, "status": "completed", "output": []}
            ).encode()
        )
        result.status = self.status
        return result

    def settimeout(self, timeout):
        pass

    def shutdown(self, how):
        pass

    def close(self):
        pass


@pytest.fixture
def connection(monkeypatch):
    Connection.requests = []
    Connection.status = 200
    Connection.identity = "resp_existing"
    monkeypatch.setattr("http.client.HTTPSConnection", Connection)
    return Connection


def test_retrieval_is_fixed_origin_get_without_generation(connection):
    result = SourcingHTTP("private-key").get("resp_existing")
    assert result["id"] == "resp_existing"
    assert connection.requests == [
        ("GET", "/v1/responses/resp_existing", {"Authorization": "Bearer private-key"})
    ]


@pytest.mark.parametrize(
    "identity",
    ["../x", "https://evil.example/x", "resp_x?secret", "resp_x/../../models", None],
)
def test_invalid_response_identity_never_connects(identity, connection):
    with pytest.raises(GatewayError, match="invalid_response_id"):
        SourcingHTTP("key").get(identity)
    assert connection.requests == []


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "authentication"),
        (403, "access_denied"),
        (404, "response_not_found"),
        (429, "rate_limit"),
        (500, "provider_http_error"),
    ],
)
def test_retrieval_errors_are_safe_and_never_retry(status, code, connection):
    connection.status = status
    with pytest.raises(GatewayError, match=code):
        SourcingHTTP("key").get("resp_existing")
    assert len(connection.requests) == 1


def test_foreign_provider_identity_is_rejected(connection):
    connection.identity = "resp_different"
    with pytest.raises(GatewayError, match="invalid_response"):
        SourcingHTTP("key").get("resp_existing")


def test_dns_stall_has_caller_deadline_and_late_connection_cannot_send(monkeypatch):
    release = threading.Event()
    requests = []

    class Stalled(Connection):
        def connect(self):
            release.wait(1)

        def request(self, *args, **kwargs):
            requests.append(args)

    monkeypatch.setattr("http.client.HTTPSConnection", Stalled)
    try:
        with pytest.raises(GatewayError, match="timeout"):
            SourcingHTTP("key").get("resp_existing", 0.02)
    finally:
        release.set()
    assert requests == []
