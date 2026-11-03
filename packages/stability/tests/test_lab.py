"""Synthetic direct-engine experiments and loopback boundary, no app/provider."""

import json
from copy import deepcopy
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from forma_stability.lab import (
    MAX_BODY,
    handler_for,
    main,
    presets,
    run_packet,
    scenario_packet,
)


@pytest.mark.parametrize(
    "name,status,margin",
    [
        ("centered", "modeled_pass", 0.05),
        ("edge", "indeterminate", 0.0),
        ("outside", "modeled_fail", -1 / 60),
        ("unknown", "needs_measurement", None),
    ],
)
def test_presets_call_actual_engine_with_independent_reference_answers(
    name, status, margin
):
    result = run_packet(scenario_packet(presets()[name]))
    report = result["report"]
    assert report["status"] == status
    assert report["physical_evidence_ids"] == []
    assert all(
        not body["mass"]["confirmed"]
        for body in result["input"]["mechanical_snapshot"]["bodies"]
    )
    if margin is None:
        assert report["overlays"] == []
    else:
        assert report["overlays"][0]["signed_margin_m"] == pytest.approx(margin)
        assert report["overlays"][0]["restoring_moment_n_m"] == pytest.approx(
            0.3 * 9.81 * margin
        )


def test_mass_scaling_and_height_limit_are_exposed_honestly():
    base = presets()["centered"]
    result = run_packet(scenario_packet(base))["report"]["overlays"][0]
    doubled = run_packet(
        scenario_packet(base | {"stand_mass_g": 200.0, "device_mass_g": 400.0})
    )["report"]["overlays"][0]
    assert doubled["center_of_mass"] == result["center_of_mass"]
    assert doubled["signed_margin_m"] == result["signed_margin_m"]
    assert doubled["restoring_moment_n_m"] == pytest.approx(
        2 * result["restoring_moment_n_m"]
    )
    high = run_packet(scenario_packet(base | {"device_z_mm": 10000.0}))["report"][
        "overlays"
    ][0]
    assert high["signed_margin_m"] == result["signed_margin_m"]
    assert high["center_of_mass"]["z"] > result["center_of_mass"]["z"]
    assert (
        run_packet(scenario_packet(base | {"required_margin_mm": 60.0}))["report"][
            "status"
        ]
        == "modeled_fail"
    )


def test_invalid_controls_and_unsupported_applicability_do_not_pass():
    base = presets()["centered"]
    for change in (
        {"width_mm": 0},
        {"device_mass_g": -1},
        {"device_y_mm": float("nan")},
        {"required_margin_mm": -1},
        {"extra": 1},
    ):
        with pytest.raises(ValueError):
            scenario_packet(base | change)
    for flag in ("rigid_assembly", "horizontal_support", "gravity_only"):
        assert (
            run_packet(scenario_packet(base | {flag: False}))["report"]["status"]
            == "unsupported"
        )


def test_advanced_input_exposes_intervals_without_finite_sampling_pass():
    packet = scenario_packet(presets()["centered"])
    mass = packet["input"]["mechanical_snapshot"]["bodies"][1]["mass"]
    mass.update(kind="interval", value=None, lower=0.1, upper=0.3)
    original = deepcopy(packet)
    assert run_packet(packet)["report"]["status"] == "indeterminate"
    assert packet == original
    with pytest.raises(ValueError, match="exactly"):
        run_packet(packet | {"arbitrary": True})


@pytest.fixture
def server():
    instance = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(0))
    instance.RequestHandlerClass = handler_for(instance.server_port)
    thread = Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{instance.server_port}"
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=3)


def post(server, path="/evaluate", value=None, **headers):
    return urlopen(
        Request(
            server + path,
            data=json.dumps(value or presets()["centered"]).encode(),
            headers={"Content-Type": "application/json", **headers},
        ),
        timeout=5,
    )


def test_http_serves_real_results_and_known_assets_only(server):
    with urlopen(server, timeout=5) as response:
        assert b"Hypothetical math experiments only" in response.read()
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    with post(server) as response:
        result = json.load(response)
        assert result["report"]["overlays"][0]["signed_margin_m"] == pytest.approx(0.05)
        assert response.headers["Cache-Control"] == "no-store"
    with post(
        server, "/evaluate-input", scenario_packet(presets()["edge"])
    ) as response:
        assert json.load(response)["report"]["status"] == "indeterminate"
    with urlopen(server + "/sample-plan", timeout=5) as response:
        sample = json.load(response)
        assert sample["plan"]["compiler_version"] == "triangular-tape-stand-v1"
    with post(
        server,
        "/inspect-plan",
        {"plan": sample["plan"], "completed_prefix": 3, "loads": None},
    ) as response:
        result = json.load(response)
        assert len(result["reference_geometry"]["facets"]) == 4
        assert result["selected_geometry"] is None
        assert result["report"] is None
    with pytest.raises(HTTPError) as error:
        urlopen(server + "/../../AGENTS.md", timeout=5)
    assert error.value.code == 404


@pytest.mark.parametrize(
    "headers,code",
    [
        ({"Origin": "https://foreign.invalid"}, 403),
        ({"Host": "foreign.invalid"}, 403),
        ({"Content-Type": "text/plain"}, 415),
        ({"Content-Length": str(MAX_BODY + 1)}, 413),
    ],
)
def test_http_rejects_foreign_origins_rebinding_and_large_requests(
    server, headers, code
):
    with pytest.raises(HTTPError) as error:
        post(server, **headers)
    assert error.value.code == code


def test_http_malformed_input_and_cli_json_roundtrip(server, tmp_path, capsys):
    with pytest.raises(HTTPError) as error:
        post(server, value={"wrong": 1})
    assert error.value.code == 422
    packet = scenario_packet(presets()["outside"])
    path = tmp_path / "case.json"
    path.write_text(json.dumps(packet), encoding="utf-8")
    main(["--input", str(path)])
    assert json.loads(capsys.readouterr().out)["report"]["status"] == "modeled_fail"
    download = run_packet(packet) | {"feedback": "Unexpected tipping outcome"}
    download["report"]["status"] = "modeled_pass"
    path.write_text(json.dumps(download), encoding="utf-8")
    main(["--input", str(path)])
    assert json.loads(capsys.readouterr().out)["report"]["status"] == "modeled_fail"
