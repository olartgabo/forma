"""Fixed-origin Responses retrieval; polling never creates another generation."""

import http.client
import json
import math
import re
import socket
import threading
import time

from forma_api.model_gateway import MAX_RESPONSE, GatewayError, MetaHTTP

RESPONSE_ID = re.compile(r"resp_[A-Za-z0-9_-]{1,160}")


def valid_response_id(value):
    return isinstance(value, str) and RESPONSE_ID.fullmatch(value) is not None


class SourcingHTTP(MetaHTTP):
    """POST retains the tested MetaHTTP deadline; GET uses the same origin/key."""

    def get(self, response_id: str, timeout: float = 30) -> dict:
        if not valid_response_id(response_id):
            raise GatewayError("invalid_response_id")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 < timeout <= 30
        ):
            raise GatewayError("invalid_timeout")
        expired = threading.Event()
        shared, outcome = {}, {}

        def work():
            try:
                outcome["result"] = self._get_once(
                    response_id, timeout, expired, shared
                )
            except Exception as exc:
                outcome["error"] = exc

        worker = threading.Thread(target=work, daemon=True, name="forma-sourcing-get")
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            expired.set()
            connection = shared.get("connection")
            sock = connection.sock if connection else None
            if sock:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            raise GatewayError("timeout")
        if "error" in outcome:
            raise outcome["error"]
        return outcome["result"]

    def _get_once(self, response_id, timeout, expired, shared):
        connection = http.client.HTTPSConnection("api.meta.ai", timeout=timeout)
        shared["connection"] = connection
        deadline = time.monotonic() + timeout
        try:
            connection.connect()
            if expired.is_set() or time.monotonic() >= deadline:
                raise GatewayError("timeout")
            if connection.sock is None:
                raise GatewayError("network_error")
            connection.request(
                "GET",
                "/v1/responses/" + response_id,
                headers={"Authorization": "Bearer " + self._key},
            )
            response = connection.getresponse()
            if response.status != 200:
                raise GatewayError(
                    {
                        401: "authentication",
                        403: "access_denied",
                        404: "response_not_found",
                        429: "rate_limit",
                    }.get(response.status, "provider_http_error")
                )
            raw = bytearray()
            while True:
                remaining = deadline - time.monotonic()
                if expired.is_set() or remaining <= 0:
                    raise GatewayError("timeout")
                if connection.sock:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_RESPONSE + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > MAX_RESPONSE:
                    raise GatewayError("response_too_large")
            result = json.loads(raw)
            if not isinstance(result, dict) or result.get("id") != response_id:
                raise GatewayError("invalid_response")
            return result
        except GatewayError:
            raise
        except (TimeoutError, socket.timeout):
            raise GatewayError("timeout") from None
        except (http.client.HTTPException, OSError):
            raise GatewayError("network_error") from None
        except (ValueError, UnicodeError):
            raise GatewayError("invalid_response") from None
        finally:
            try:
                connection.close()
            except OSError:
                pass
