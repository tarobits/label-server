"""Retry-safe REST client. Same event = same key; intentional reprint = new key."""

import argparse
import json
import time
import urllib.error
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="http://localhost:8000")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--template", default="text")
    parser.add_argument("--key", required=True, help="Stable identifier of the originating event")
    parser.add_argument("--data", required=True, help="JSON object of template field values")
    parser.add_argument("--copies", type=int, default=1)
    args = parser.parse_args()
    body = json.dumps(
        {
            "tape_profile": args.profile,
            "template": args.template,
            "copies": args.copies,
            "data": json.loads(args.data),
        }
    ).encode()
    request = urllib.request.Request(
        args.server.rstrip("/") + "/api/jobs",
        data=body,
        headers={"Content-Type": "application/json", "Idempotency-Key": args.key},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                print(response.read().decode())
                return
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt == 2:
                raise SystemExit(error.read().decode()) from error
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == 2:
                raise SystemExit(str(error)) from error
        time.sleep(2**attempt)


if __name__ == "__main__":
    main()
