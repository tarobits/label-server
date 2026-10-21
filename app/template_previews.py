"""Persistent WebP thumbnails, keyed by template revision and missing dependencies."""

import hashlib
import io
import json
import tempfile
from pathlib import Path
from threading import RLock

from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from app.font_assets import FontStore
from app.image_assets import ImageStore
from app.models import LabelTemplate
from app.render import RenderSpec, render_document
from app.template_schema import TemplateDocument


class TemplatePreviews:
    def __init__(self, root: Path):
        self.root = root
        self.lock = RLock()

    @staticmethod
    def prefix(identifier: str) -> str:
        return hashlib.sha256(identifier.encode()).hexdigest()

    def invalidate(self, identifier: str, *, keep: Path | None = None) -> None:
        with self.lock:
            if self.root.exists():
                for path in self.root.glob(f"{self.prefix(identifier)}-*"):
                    if path != keep:
                        path.unlink(missing_ok=True)

    def get(
        self,
        template: LabelTemplate,
        notices: list[dict[str, str]],
        fonts: FontStore,
        images: ImageStore,
    ) -> bytes:
        key = hashlib.sha256(
            json.dumps(
                {
                    "revision": template.revision,
                    "document": template.document,
                    "missing": sorted((notice["kind"], notice["id"]) for notice in notices),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        path = self.root / f"{self.prefix(template.id)}-{key}.webp"
        with self.lock:
            if path.is_file():
                return path.read_bytes()
            document = TemplateDocument.model_validate(template.document)
            output = render_document(
                document,
                {},
                RenderSpec(stretch_canvas=True),
                samples=True,
                fonts=fonts,
                images=images,
                allow_missing_assets=True,
            )
            tape = document.preview_tape
            image = ImageOps.colorize(
                output.image.convert("L"),
                tape.foreground if tape else "#000000",
                tape.background if tape else "#ffffff",
            )
            image.thumbnail((960, 384), Image.Resampling.LANCZOS)
            encoded = io.BytesIO()
            image.save(encoded, format="WEBP", lossless=True)
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                dir=self.root, prefix=f"{self.prefix(template.id)}-", suffix=".tmp", delete=False
            ) as target:
                temporary = Path(target.name)
                try:
                    target.write(encoded.getvalue())
                    target.flush()
                    self.invalidate(template.id, keep=temporary)
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
            return encoded.getvalue()


def invalidate_deleted_previews(session: Session, root: Path, kind: str, identifier: str) -> None:
    """Purge derived images together with the original retained content."""
    from sqlalchemy import select

    from app.asset_access import asset_references

    previews = TemplatePreviews(root)
    if kind == "templates":
        previews.invalidate(identifier)
    elif kind in ("images", "fonts"):
        reference = ("image_asset" if kind == "images" else "font_asset", identifier)
        for template in session.scalars(select(LabelTemplate)):
            if reference in asset_references(template.document):
                previews.invalidate(template.id)
