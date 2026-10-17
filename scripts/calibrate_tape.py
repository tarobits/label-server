"""Prepare or print one PT-P710BT calibration batch on 24 mm tape.

Stop the server and other printer applications first. Direct calibration prints
do not create queue records or deduct tape from cartridge inventory.
"""

import argparse
import fcntl
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.engine import make_url

from app.config import Settings
from app.printer.base import PrintInterrupted, PrintNotStarted, RenderedLabel
from app.printer.brother import PRODUCT_ID, VENDOR_ID, BrotherPTP710BT, encode_raster
from app.printer.usb import UsbTransport


def calibration_labels(copies: int, cut: str, dpi_x: int) -> list[RenderedLabel]:
    """Fixed 60 mm bodies; markings stay inside the 24 mm tape's print band."""
    font = ImageFont.truetype(
        str(Path(__file__).resolve().parents[1] / "app/fonts/NotoSans.ttf"), 22
    )
    labels = []
    for number in range(1, copies + 1):
        image = Image.new("1", (round(60 * 180 / 25.4), round(24 * 180 / 25.4)))
        draw = ImageDraw.Draw(image)
        draw.text(
            (image.width // 2, image.height // 2),
            f"{cut} {number}/{copies}",
            font=font,
            fill=1,
            anchor="mm",
        )
        # A 50 mm rule, inset 5 mm from each end of the nominal label body.
        x1, x2, y = round(5 * 180 / 25.4), round(55 * 180 / 25.4), 120
        draw.line((x1, y, x2, y), fill=1, width=2)
        for x in (x1, x2):
            draw.line((x, y - 5, x, y + 5), fill=1, width=2)
        if dpi_x != 180:
            image = image.resize((round(60 * dpi_x / 25.4), image.height), Image.Resampling.NEAREST)
        label = RenderedLabel(
            f"calibration-{number}",
            24,
            60,
            image.width,
            image.height,
            image.tobytes(),
            dpi_x=dpi_x,
        )
        encode_raster(label)  # Validate the whole batch before any USB access.
        labels.append(label)
    return labels


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--copies", type=int, choices=(1, 3), default=1)
    parser.add_argument("--cut", choices=("each", "strip"), default="each")
    parser.add_argument("--resolution", choices=("normal", "high"), default="normal")
    parser.add_argument(
        "--print",
        dest="print_now",
        action="store_true",
        help="Physically print this batch; default only shows its estimate",
    )
    args = parser.parse_args(argv)
    dpi_x = 360 if args.resolution == "high" else 180
    labels = calibration_labels(args.copies, args.cut, dpi_x)
    backend = BrotherPTP710BT(
        UsbTransport(VENDOR_ID, PRODUCT_ID, args.serial),
        feed_mm=2,
        leader_mm=24.5,
        cut_each=args.cut == "each",
    )
    print(
        json.dumps(
            {
                "serial": args.serial,
                "copies": args.copies,
                "cut": args.cut,
                "label_length_mm": 60,
                "dpi_along_tape": dpi_x,
                "dpi_across_tape": 180,
                "feed_setting_mm": 2,
                "leader_estimate_mm": 24.5,
                "estimated_total_mm": round(backend.estimate_consumption(labels), 3),
            },
            indent=2,
        ),
        flush=True,
    )
    if not args.print_now:
        print("Estimate only. Add --print to physically print this batch.")
        return 0

    database = make_url(Settings().database_url).database
    if not database or database == ":memory:":
        parser.error("A local file-backed database is required for the server ownership lock")
    lock_path = Path(database).resolve().with_suffix(".worker.lock")
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Stop the label server before running direct calibration prints.")
            return 1
        status = backend.get_status()
        if not status.connected or status.error or status.tape_width_mm != 24:
            print(f"Not printing: a ready printer with 24 mm tape is required. {status}")
            return 1
        try:
            backend.print_batch(labels)
        except PrintNotStarted as error:
            print(f"Nothing printed: {error}")
            return 1
        except (PrintInterrupted, KeyboardInterrupt) as error:
            print(f"Output is uncertain: {error}. Inspect all output; no automatic retry.")
            return 1
    print("Completed. Measure all emitted tape, including blank leaders, in millimetres.")
    print("This direct print did not update the queue or cartridge estimate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
