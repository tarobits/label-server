"""Create a frozen quality-test draft through the API. Never submits or prints it."""

import argparse
import json
import urllib.request
import uuid

try:
    from scripts.api_session import open_authenticated
except ModuleNotFoundError:
    from api_session import open_authenticated


def request(server, path, body, raw=False):
    data = body if raw else json.dumps(body).encode()
    with open_authenticated(
        urllib.request.Request(
            server.rstrip("/") + "/api" + path,
            data=data,
            headers={"Content-Type": "application/octet-stream" if raw else "application/json"},
        ),
        timeout=30,
    ) as result:
        return json.load(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://localhost:8000")
    parser.add_argument("--profile", required=True, help="A 24 mm tape profile ID")
    parser.add_argument(
        "--destination", help="Printer or group ID (required when several printers exist)"
    )
    args = parser.parse_args()
    image = request(
        args.server,
        "/image-assets?name=Quality-test",
        b'<svg viewBox="0 0 100 40"><circle cx="20" cy="20" r="18" fill="none" stroke="black" stroke-width="2"/><path d="M0 40L40 0" stroke="black"/><rect x="45" width="15" height="40" fill="#444444"/><rect x="60" width="15" height="40" fill="#888888"/><rect x="75" width="15" height="40" fill="#cccccc"/></svg>',
        True,
    )
    elements = [
        {
            "id": "title",
            "kind": "text",
            "x": 2,
            "y": 3.2,
            "width": 48,
            "height": 5,
            "font_size": 3,
            "content": "{{text}}",
        },
        {
            "id": "small",
            "kind": "text",
            "x": 2,
            "y": 9,
            "width": 48,
            "height": 5,
            "font_size": 2,
            "content": "AaBb 0123456789 / →",
        },
        {
            "id": "qr",
            "kind": "qr",
            "x": 52,
            "y": 4,
            "width": 16,
            "height": 16,
            "content": "https://example.org",
            "qr_fill_box": True,
        },
        {
            "id": "art",
            "kind": "image",
            "x": 70,
            "y": 5,
            "width": 30,
            "height": 12,
            "image_asset": image["id"],
            "image_mode": "dither",
        },
        {"id": "ruler", "kind": "line", "x": 2, "y": 18, "width": 10, "height": 1, "stroke": 0.2},
    ]
    # Noto Sans may not include every arrow glyph; use ASCII to keep the fixture portable.
    elements[1]["content"] = "AaBb 0123456789 / ->"
    template = request(
        args.server,
        "/templates",
        {
            "destination_id": args.destination,
            "name": "Physical quality acceptance",
            "document": {
                "width_mm": 24,
                "length_mm": 102,
                "elements": elements,
                "fields": [{"name": "text", "label": "Sample", "sample": "Quality / 01"}],
            },
        },
    )
    prepared = request(
        args.server,
        "/runs/prepare",
        {
            "destination_id": args.destination,
            "request_key": str(uuid.uuid4()),
            "name": "Physical verification: three ordered labels",
            "template": template["id"],
            "expected_revision": template["revision"],
            "tape_profile": args.profile,
            "csv_text": "Text\nQuality / 01\nQuality / 02\nQuality / 03\n",
            "mapping": {"text": "Text"},
            "rows": [{"source_row": row, "copies": 1} for row in (2, 3, 4)],
        },
    )
    if not prepared.get("valid"):
        raise SystemExit(json.dumps(prepared))
    print(args.server.rstrip("/") + "/#/runs/" + prepared["run"]["id"])


if __name__ == "__main__":
    main()
