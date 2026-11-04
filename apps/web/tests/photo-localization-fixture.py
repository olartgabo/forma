"""Export real scoped API outputs using a scripted SAM transport, offline only."""

import base64
import json
import sys
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from forma_api import photo_localization
from forma_api.main import create_app
from forma_api.model_gateway import MetaGateway


class ScriptedTransport:
    def post(self, path, payload, timeout):
        assert path == "/responses" and payload["model"] == "sam-3.1"
        return {
            "status": "completed",
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": "<0f>0<|box;x1=80;y1=90;x2=420;y2=310;w=600;h=400|>",
                        }
                    ]
                }
            ],
        }


with TemporaryDirectory() as directory:
    token = "synthetic-owner-credential-0000000001"
    headers = {"Authorization": "Bearer " + token}
    photo_localization.default_gateway_factory = lambda: MetaGateway(
        ScriptedTransport()
    )
    with TestClient(create_app(Path(directory), {"synthetic": token})) as client:
        p = client.post(
            "/api/projects",
            headers=headers,
            json={
                "goal": "SYNTHETIC software fixture: identify a cardboard sheet",
                "idempotency_key": "fixture-project-001",
            },
        ).json()["project"]
        image = Image.new("RGB", (600, 400), "#efebe3")
        draw = ImageDraw.Draw(image)
        draw.rectangle((80, 90, 420, 310), fill="#b78c58", outline="#795a39", width=3)
        draw.text((85, 45), "SYNTHETIC SOFTWARE TEST IMAGE", fill="#282828")
        draw.rectangle((460, 120, 500, 290), fill="#d2c597")
        stream = BytesIO()
        image.save(stream, format="PNG")
        photo = client.post(
            f"/api/projects/{p['id']}/media",
            headers={
                **headers,
                "Content-Type": "image/png",
                "Idempotency-Key": "fixture-photo-001",
            },
            content=stream.getvalue(),
        ).json()["media"]
        body = dict(
            media_id=photo["id"],
            expected_revision_id=p["revision_id"],
            concept="cardboard sheet",
            provider_transfer_consented=True,
            idempotency_key="fixture-localization-001",
        )
        result = client.post(
            f"/api/projects/{p['id']}/photo-localizations", headers=headers, json=body
        )
        assert result.status_code == 200, result.text
        readiness = client.get(
            f"/api/projects/{p['id']}/designs/readiness", headers=headers
        )
        assert readiness.status_code == 200, readiness.text
        fixture = dict(
            project=p,
            photo=photo,
            result=result.json(),
            readiness=readiness.json(),
            image_base64=base64.b64encode(stream.getvalue()).decode(),
        )
        Path(sys.argv[1]).write_text(json.dumps(fixture), encoding="utf-8")
