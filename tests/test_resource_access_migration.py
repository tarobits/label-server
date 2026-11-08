from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select

from app.db import make_engine, session_factory
from app.models import (
    AuditEvent,
    Cartridge,
    Location,
    PrinterDevice,
    ResourceGrant,
    Role,
    TapeProfile,
)


def test_resource_foundation_upgrade_preserves_inventory_and_does_not_claim_it(tmp_path):
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    config = Config("alembic.ini")
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    engine = make_engine(url)
    factory = session_factory(engine)
    permissions = [{"kind": "destination", "destination_id": "p", "level": "moderator"}]
    with factory.begin() as session:
        session.add(TapeProfile(id="t", name="Tape", width_mm=24))
        session.add(PrinterDevice(id="p", name="Printer", driver="mock", config={}))
        session.add(Role(id="custom", name="Custom", permissions=permissions))
        session.flush()
        session.add(
            Cartridge(
                id="c",
                profile_id="t",
                name="Saved cartridge",
                nominal_length_mm=8000,
                remaining_mm=1234,
                price_minor=1299,
                currency="EUR",
            )
        )
    # Model a fully populated prior-release installation, then upgrade it.
    command.downgrade(config, "c94f6b821e35")
    assert "owner_id" not in {
        column["name"] for column in inspect(engine).get_columns("cartridges")
    }
    command.upgrade(config, "head")
    command.check(config)
    with factory() as session:
        cartridge = session.get(Cartridge, "c")
        assert cartridge is not None
        assert cartridge.remaining_mm == 1234
        assert cartridge.price_minor == 1299
        assert cartridge.currency == "EUR"
        assert cartridge.owner_id is None and cartridge.location_id is None
        assert cartridge.notes == ""
        printer = session.get(PrinterDevice, "p")
        assert printer is not None
        assert printer.owner_id is None and printer.location_id is None
        assert session.get_one(Role, "custom").permissions == permissions
        assert session.scalars(select(ResourceGrant)).all() == []
        assert session.scalars(select(AuditEvent)).all() == []
    with factory.begin() as session:
        session.add(Location(id="room", name="Room"))
        session.flush()
        session.get_one(Cartridge, "c").location_id = "room"
        session.get_one(PrinterDevice, "p").location_id = "room"
    # Downgrade must also work when nullable foreign keys are populated.
    command.downgrade(config, "c94f6b821e35")
    command.upgrade(config, "head")
    command.check(config)
    with factory() as session:
        assert session.get_one(Cartridge, "c").remaining_mm == 1234
    engine.dispose()
