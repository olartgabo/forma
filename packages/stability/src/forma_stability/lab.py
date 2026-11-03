"""Loopback-only hypothetical workbench for the real pure stability evaluator."""

import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from forma_domain.stability_contracts import AnalysisPolicy, StabilityInput
from forma_stability import evaluate_stability

MAX_BODY = 131072
Finite = Annotated[float, Field(allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class Scenario(BaseModel):
    """Diagnostic controls only: all entries are hypothetical, never evidence."""

    model_config = ConfigDict(extra="forbid")
    width_mm: Positive
    depth_mm: Positive
    stand_mass_g: Positive | None
    device_mass_g: Positive | None
    stand_x_mm: Finite | None
    stand_y_mm: Finite | None
    stand_z_mm: Finite | None
    device_x_mm: Finite | None
    device_y_mm: Finite | None
    device_z_mm: Finite | None
    required_margin_mm: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    tolerance_mm: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    gravity_m_s2: Positive
    rigid_assembly: bool
    horizontal_support: bool
    gravity_only: bool


def presets():
    centered = dict(
        width_mm=200.0,
        depth_mm=100.0,
        stand_mass_g=100.0,
        device_mass_g=200.0,
        stand_x_mm=0.0,
        stand_y_mm=0.0,
        stand_z_mm=30.0,
        device_x_mm=0.0,
        device_y_mm=0.0,
        device_z_mm=100.0,
        required_margin_mm=0.0,
        tolerance_mm=0.000001,
        gravity_m_s2=9.81,
        rigid_assembly=True,
        horizontal_support=True,
        gravity_only=True,
    )
    return {
        "centered": centered,
        "edge": centered | {"device_y_mm": 75.0},
        "outside": centered | {"device_y_mm": 100.0},
        "unknown": centered | {"device_mass_g": None},
    }


def scenario_packet(value):
    s = Scenario.model_validate(value)

    def quantity(number, unit, divisor=1):
        if number is None:
            return dict(
                kind="unknown", unit=unit, provenance="unknown", confirmed=False
            )
        return dict(
            kind="scalar",
            unit=unit,
            value=number / divisor,
            provenance="assumed",
            confirmed=False,
        )

    def body(name, kind, sources):
        return dict(
            body_id=name,
            body_kind=kind,
            source_part_ids=sources,
            mass=quantity(getattr(s, name + "_mass_g"), "kg", 1000),
            center_of_mass={
                axis: quantity(getattr(s, f"{name}_{axis}_mm"), "m", 1000)
                for axis in ("x", "y", "z")
            },
        )

    w, d = s.width_mm / 2000, s.depth_mm / 2000
    digest = hashlib.sha256(s.model_dump_json().encode()).hexdigest()
    analysis = StabilityInput.model_validate(
        dict(
            identity=dict(
                project_id="hypothetical-lab",
                plan_version_id="not-a-build-plan",
                inventory_revision="not-an-inventory",
                history_cursor=None,
                operation_state_id="hypothetical-rigid-body",
                canonical_geometry_hash=digest,
                evidence_hash=hashlib.sha256(b"no-evidence").hexdigest(),
                profile_hash=hashlib.sha256(b"no-material-profile").hexdigest(),
            ),
            geometry_version="lab-rectangle-v1",
            profile_version="hypothetical-v1",
            mechanical_snapshot=dict(
                bodies=[
                    body("stand", "stand_part", ["hypothetical-complete-stand"]),
                    body("device", "device", []),
                ],
                contacts=[
                    dict(
                        contact_id="rectangle",
                        body_id="stand",
                        active=True,
                        polygon_world=[
                            dict(x=x, y=y, z=0.0)
                            for x, y in [(-w, -d), (w, -d), (w, d), (-w, d)]
                        ],
                        assumption_ids=["hypothetical-full-rectangle-contact"],
                    )
                ],
                rigid_assembly=s.rigid_assembly,
                horizontal_support=s.horizontal_support,
                gravity_only=s.gravity_only,
                state_basis="nominal",
                assumption_ids=["hypothetical-inputs-not-measurements"],
            ),
            cases=[
                dict(
                    case_id="lab-case",
                    orientation="User-edited hypothetical world pose",
                    body_ids=["stand", "device"],
                    contact_ids=["rectangle"],
                    gravity_m_s2=quantity(s.gravity_m_s2, "m_s2"),
                )
            ],
        )
    )
    policy = AnalysisPolicy(
        policy_id="lab-explicit-policy",
        version="v1",
        length_tolerance_m=s.tolerance_mm / 1000,
        force_tolerance_n=0.0,
        moment_tolerance_n_m=0.0,
        relative_tolerance=0.0,
        required_margin_m=s.required_margin_mm / 1000,
        uncertainty_method="analytic_interval",
        evaluation_budget=16,
        required_check_types=("support", "tip"),
        required_case_ids=("lab-case",),
    )
    return dict(
        input=analysis.model_dump(mode="json"), policy=policy.model_dump(mode="json")
    )


def run_packet(packet):
    if not isinstance(packet, dict) or set(packet) != {"input", "policy"}:
        raise ValueError("Provide exactly input and policy fields")
    analysis = StabilityInput.model_validate(packet["input"])
    policy = AnalysisPolicy.model_validate(packet["policy"])
    report = evaluate_stability(analysis, policy)
    return dict(
        label="HYPOTHETICAL ENGINE EXPERIMENT - not authenticated evidence or a physical pass",
        input=analysis.model_dump(mode="json"),
        policy=policy.model_dump(mode="json"),
        report=report.model_dump(mode="json"),
    )


def handler_for(port):
    authority = f"127.0.0.1:{port}"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Input values stay out of request logs.

        def reply(self, status, body, mime="application/json"):
            encoded = (
                body
                if isinstance(body, bytes)
                else json.dumps(body, allow_nan=False).encode()
            )
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(encoded)

        def authorized_origin(self):
            return self.headers.get("Host") == authority and self.headers.get(
                "Origin"
            ) in (None, f"http://{authority}")

        def do_GET(self):
            if not self.authorized_origin():
                return self.reply(403, {"error": "Use the printed loopback address"})
            if self.path == "/presets":
                return self.reply(200, presets())
            if self.path == "/sample-plan":
                return self.reply(
                    200,
                    json.loads(
                        Path(__file__)
                        .with_name("lab-stand-plan.json")
                        .read_text(encoding="utf-8")
                    ),
                )
            asset = {
                "/": ("lab.html", "text/html; charset=utf-8"),
                "/lab.js": ("lab.js", "text/javascript; charset=utf-8"),
                "/lab-plan.js": ("lab-plan.js", "text/javascript; charset=utf-8"),
                "/lab.css": ("lab.css", "text/css; charset=utf-8"),
            }.get(self.path)
            if asset is None:
                return self.reply(404, {"error": "Not found"})
            return self.reply(
                200, Path(__file__).with_name(asset[0]).read_bytes(), asset[1]
            )

        def do_POST(self):
            if not self.authorized_origin():
                return self.reply(
                    403, {"error": "Cross-origin requests are not accepted"}
                )
            if self.path not in ("/evaluate", "/evaluate-input", "/inspect-plan"):
                return self.reply(404, {"error": "Not found"})
            if (
                self.headers.get("Content-Type", "").split(";", 1)[0]
                != "application/json"
            ):
                return self.reply(415, {"error": "JSON required"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                size = 0
            if not 0 < size <= MAX_BODY or self.headers.get("Transfer-Encoding"):
                return self.reply(413, {"error": "JSON body must be 1..131072 bytes"})
            self.connection.settimeout(5)
            try:
                data = json.loads(self.rfile.read(size))
                if self.path == "/inspect-plan":
                    from forma_stability.lab_plan import inspect_plan

                    result = inspect_plan(data)
                else:
                    packet = scenario_packet(data) if self.path == "/evaluate" else data
                    result = run_packet(packet)
            except (ValueError, ValidationError, TimeoutError) as error:
                return self.reply(422, {"error": str(error)[:4000]})
            self.reply(200, result)

    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--lab", action="store_true", help="Open a local engine workbench server"
    )
    mode.add_argument(
        "--input", type=Path, help="Evaluate a JSON file with input and policy"
    )
    mode.add_argument(
        "--plan-input",
        type=Path,
        help="Replay a compiled-plan lab request or downloaded feedback bundle",
    )
    parser.add_argument("--port", type=int, default=3031)
    args = parser.parse_args(argv)
    if args.plan_input:
        from forma_stability.lab_plan import inspect_plan

        try:
            if args.plan_input.stat().st_size > MAX_BODY:
                parser.error("Input exceeds 131072 bytes")
            payload = json.loads(args.plan_input.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and "request" in payload:
                payload = payload["request"]
            print(json.dumps(inspect_plan(payload), indent=2, allow_nan=False))
        except (OSError, ValueError, ValidationError) as error:
            parser.error(str(error))
        return
    if args.input:
        try:
            if args.input.stat().st_size > MAX_BODY:
                parser.error("Input exceeds 131072 bytes")
            packet = json.loads(args.input.read_text(encoding="utf-8"))
            if (
                isinstance(packet, dict)
                and {"input", "policy", "report"} <= packet.keys()
                and packet.keys() <= {"input", "policy", "report", "label", "feedback"}
            ):
                # A downloaded feedback bundle is replayed from its inputs.
                # Never trust or reuse its stored report as a calculation.
                packet = {key: packet[key] for key in ("input", "policy")}
            result = run_packet(packet)
        except (OSError, ValueError, ValidationError) as error:
            parser.error(str(error))
        print(json.dumps(result, indent=2, allow_nan=False))
        return
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    with ThreadingHTTPServer(
        ("127.0.0.1", args.port), handler_for(args.port)
    ) as server:
        server.daemon_threads = True
        print(
            f"Engine lab: http://127.0.0.1:{args.port} (hypothetical only; Ctrl+C to stop)",
            flush=True,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
