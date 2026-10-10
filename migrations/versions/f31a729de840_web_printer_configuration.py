"""Move the legacy printer configuration into an ordinary persistent registration.

Revision ID: f31a729de840
Revises: e51f038b02cd
"""

import sqlalchemy as sa
from alembic import op
from pydantic_settings import BaseSettings, SettingsConfigDict

revision = "f31a729de840"
down_revision = "e51f038b02cd"
branch_labels = None
depends_on = None


class LegacySettings(BaseSettings):
    # Read once during upgrade, never during normal application startup.
    model_config = SettingsConfigDict(env_prefix="LABEL_", env_file=".env", extra="ignore")
    printer_backend: str = "mock"
    printer_usb_serial: str | None = None
    printer_resolution: str = "normal"
    printer_timeout_seconds: float = 120
    printer_feed_mm: float = 2
    printer_leader_mm: float = 24.5
    printer_cut_each: bool = True


def upgrade():
    connection = op.get_bind()
    printers = sa.Table("printers", sa.MetaData(), autoload_with=connection)
    for device in connection.execute(
        printers.select().where(printers.c.driver == "mock")
    ).mappings():
        connection.execute(
            printers.update()
            .where(printers.c.id == device["id"])
            .values(config={**device["config"], "retired": True})
        )
    existing = (
        connection.execute(printers.select().where(printers.c.id == "main")).mappings().first()
    )
    legacy_state = connection.execute(
        sa.text("SELECT id FROM printer_state WHERE printer_id = 'main'")
    ).first()
    if existing is None and legacy_state is None:
        return  # A fresh installation has no implicit printer.
    settings = LegacySettings()
    config = {
        "usb_serial": settings.printer_usb_serial,
        "resolution": settings.printer_resolution,
        "timeout_seconds": settings.printer_timeout_seconds,
        "feed_mm": settings.printer_feed_mm,
        "leader_mm": settings.printer_leader_mm,
        "cut_each": settings.printer_cut_each,
    }
    if (existing and existing["driver"] == "mock") or (
        not existing and settings.printer_backend == "mock"
    ):
        config["retired"] = True
    if existing:
        config.update(existing["config"])
        connection.execute(printers.update().where(printers.c.id == "main").values(config=config))
    else:
        connection.execute(
            printers.insert().values(
                id="main",
                name="Imported printer",
                driver=settings.printer_backend,
                config=config,
            )
        )


def downgrade():
    # Retain registrations and user changes; the preceding schema is identical.
    pass
