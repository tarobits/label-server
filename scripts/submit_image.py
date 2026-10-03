"""Submit an image label, or save a print-pixel preview without queuing it.

Standalone Python 3 client; no server package or third-party dependencies needed.
"""

import argparse
import base64
import hashlib
import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MAX_IMAGE_BYTES = 5_000_000


def request(server, path, data, *, key=None, raw=False):
    headers = {"Content-Type": "application/octet-stream" if raw else "application/json"}
    if key:
        headers["Idempotency-Key"] = key
    message = urllib.request.Request(
        server.rstrip("/") + "/api" + path,
        data=data if raw else json.dumps(data).encode(),
        headers=headers,
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(message, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt == 2:
                raise SystemExit(error.read().decode()) from error
            error.close()
        except (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            http.client.IncompleteRead,
        ) as error:
            if attempt == 2:
                raise SystemExit(str(error)) from error
        time.sleep(2**attempt)


def homebox_key(path: Path, data: bytes) -> str:
    # HomeBox gives each print invocation a fresh temporary filename. Content-only
    # keys would incorrectly suppress intentional reprints of the same label.
    digest = hashlib.sha256(str(path.resolve()).encode() + b"\0" + data).hexdigest()
    return "homebox:" + digest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--server", default="http://localhost:8000")
    parser.add_argument("--profile", required=True)
    keys = parser.add_mutually_exclusive_group()
    keys.add_argument("--key", help="Stable originating event ID; use a new key for a reprint")
    keys.add_argument(
        "--homebox", action="store_true", help="Derive key from HomeBox's temporary file"
    )
    parser.add_argument("--copies", type=int, default=1)
    parser.add_argument("--length", type=float, help="Fit within this length in mm (10–300)")
    parser.add_argument("--resolution", choices=("printer", "normal", "high"), default="printer")
    parser.add_argument("--mode", choices=("threshold", "dither"), default="threshold")
    parser.add_argument("--threshold", type=int, default=128)
    parser.add_argument(
        "--preview", type=Path, help="Save an HTML pixel preview; do not queue a job"
    )
    args = parser.parse_args(argv)
    if not args.preview and not (args.key or args.homebox):
        parser.error("Submission requires --key or --homebox")
    if args.key and not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", args.key):
        parser.error("Key must be 1–128 letters, digits, dots, colons, underscores or hyphens")
    if not 1 <= args.copies <= 1000 or not 1 <= args.threshold <= 255:
        parser.error("Copies must be 1–1000 and threshold must be 1–255")
    if args.length is not None and not 10 <= args.length <= 300:
        parser.error("Length must be 10–300 mm")
    try:
        with args.file.open("rb") as source:
            data = source.read(MAX_IMAGE_BYTES + 1)
    except OSError as error:
        parser.error(str(error))
    if not data or len(data) > MAX_IMAGE_BYTES:
        parser.error("Image must be nonempty and at most 5 MB")
    key = homebox_key(args.file, data) if args.homebox else args.key
    # Uploads are content-addressed, so retrying this first step creates no duplicates.
    asset = request(
        args.server,
        "/image-assets?" + urllib.parse.urlencode({"name": args.file.name}),
        data,
        raw=True,
    )
    body = {
        "image_asset": asset["id"],
        "tape_profile": args.profile,
        "copies": args.copies,
        "length_mm": args.length,
        "print_resolution": args.resolution,
        "image_mode": args.mode,
        "image_threshold": args.threshold,
    }
    if args.preview:
        result = request(args.server, "/image-jobs/preview", body)
        # Re-encode the data URI and coerce dimensions before embedding server data.
        png = base64.b64encode(base64.b64decode(result["png"].split(",", 1)[1])).decode()
        length, width = float(result["length_mm"]), float(result["width_mm"])
        args.preview.write_text(
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            '<title>Image label preview</title><body style="background:#101827;color:#eee;'
            'font:16px system-ui;padding:2rem">'
            f"<p>{length:g} × {width:g} mm · print pixels · no job queued</p>"
            f'<img alt="Label print preview" src="data:image/png;base64,{png}" '
            f'style="width:min(100%,900px);aspect-ratio:{length}/{width};'
            'image-rendering:pixelated"></body></html>',
            encoding="utf-8",
        )
        print(f"Preview saved to {args.preview}; no job queued")
    else:
        print(json.dumps(request(args.server, "/image-jobs", body, key=key)))


if __name__ == "__main__":
    main()
