"""Generate install icons from the existing vector favicon.

Run with .venv/bin/python scripts/generate_app_icons.py after changing favicon.svg.
"""

from pathlib import Path
from xml.etree import ElementTree

import resvg_py


def main() -> None:
    public = Path(__file__).resolve().parents[1] / "frontend" / "public"
    source = (public / "favicon.svg").read_text()
    for size in (192, 512):
        (public / f"pwa-{size}x{size}.png").write_bytes(
            resvg_py.svg_to_bytes(svg_string=source, width=size, height=size)
        )

    # Let the OS crop the background. The existing centered printer glyph fits
    # inside the maskable icon's safe circle (40% of the image width in radius).
    maskable = ElementTree.fromstring(source)
    background = maskable.find("{http://www.w3.org/2000/svg}rect")
    if background is None:
        raise ValueError("The favicon must have a background rectangle")
    background.set("rx", "0")
    (public / "pwa-maskable-512x512.png").write_bytes(
        resvg_py.svg_to_bytes(
            svg_string=ElementTree.tostring(maskable, encoding="unicode"), width=512, height=512
        )
    )


if __name__ == "__main__":
    main()
