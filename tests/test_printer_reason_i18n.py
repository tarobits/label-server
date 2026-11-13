"""Printer reasons survive serialization without trusting metadata over hardware state."""

import json
from dataclasses import asdict

import pytest
from sqlalchemy import select

from app.audit.action_audit import record_action
from app.audit.audit import project_audit
from app.authn.resource_access import ResourceAccess
from app.companion.companion_transport_api import DeviceStatus
from app.i18n import Message, translate
from app.models import AuditEvent, PrinterState
from app.printer.base import PrinterStatus
from app.printer.brother import StatusPacket
from app.printer.messages import localize_status, restore_reason
from app.printing.queue import record_blocker


def test_all_fault_bits_survive_wire_and_language_changes():
    packet = StatusPacket(24, 1, 0, 0, (0x84, 0x10))
    status = PrinterStatus(True, 24, packet.hardware_problem)
    wire = json.loads(json.dumps(asdict(status)))
    parsed = DeviceStatus.model_validate(wire)
    restored = PrinterStatus(**parsed.model_dump(exclude={"local_blocked", "clearance_seen"}))
    german = translate(restored.localized_error, "de")
    assert "Schneidevorrichtung blockiert" in german
    assert "Abdeckung offen" in german
    assert "Unbekannter Fehler in Byte 1, Bit 0x80" in german
    assert "84/10" in german
    assert translate(restored.localized_error, "en") == status.error
    assert restored.error_requires_investigation
    assert localize_status(wire, "de")["error"] == german
    assert wire["error"] == status.error  # One viewer cannot mutate another viewer's cache.


@pytest.mark.parametrize(
    "metadata",
    [
        {"key": "account.language"},
        {"key": "printerMessages.coverOpen", "parameters": []},
        {"key": "printerMessages.coverOpen", "parameters": {"evil": {"key": "account.language"}}},
        {"key": "printerMessages.coverOpen"},  # Valid key but different recorded fault.
        {"messages": [None]},
        {"messages": [], "separator": "x" * 9000},
    ],
)
def test_bad_metadata_cannot_hide_fault_or_poison_next_status(metadata):
    status = DeviceStatus(connected=True, error="Historical fault", error_translation=metadata)
    assert status.error_translation is None
    assert status.error == "Historical fault"
    assert status.error_requires_investigation
    good = PrinterStatus(True, 24, Message("printerMessages.coverOpen"))
    assert DeviceStatus(**asdict(good)).error_translation
    assert translate(good.localized_error, "de") == "Abdeckung offen"


def test_persisted_blocker_language_legacy_and_clear_recovery(client):
    factory = client.app.state.factory
    reason = Message(
        "printerMessages.investigationReason", reason=Message("printerMessages.coverOpen")
    )
    with factory.begin() as session:
        state = session.scalar(select(PrinterState).where(PrinterState.printer_id == "main"))
        record_blocker(session, state, reason)
    # A new session reconstructs the reason from JSON, not an in-memory Message.
    with factory.begin() as session:
        state = session.scalar(select(PrinterState).where(PrinterState.printer_id == "main"))
        assert (
            translate(restore_reason(state.blocker, state.blocker_translation), "de")
            == "Companion-Drucker muss überprüft werden: Abdeckung offen"
        )
        record_blocker(session, state, "Historical fault")
        assert state.blocker_translation is None
    with factory.begin() as session:
        state = session.scalar(select(PrinterState).where(PrinterState.printer_id == "main"))
        assert restore_reason(state.blocker, state.blocker_translation) == "Historical fault"
        record_blocker(session, state, None)
        assert state.blocker is None and state.blocker_translation is None
        record_blocker(session, state, Message("printerMessages.disconnected"))
    response = client.get("/api/printers/status", headers={"Accept-Language": "de"})
    assert response.status_code == 200
    assert "Drucker getrennt" in response.text


def test_translated_audit_reason_keeps_field_authorization(client):
    factory = client.app.state.factory
    with factory.begin() as session:
        record_action(
            session,
            "companion.printer_blocked",
            "printer",
            "main",
            {
                "reason": Message(
                    "printerMessages.reportedFault", reason=Message("printerMessages.coverOpen")
                ),
                "connected": True,
                "local_blocked": False,
            },
        )
    with factory() as session:
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "companion.printer_blocked")
        )
        admin = ResourceAccess(
            "admin", True, frozenset(), {("printer", "main"): frozenset({"printer.view"})}
        )
        translated = project_audit(event, admin, "de")
        assert translated is not None
        assert (
            translated["fields"]["reason"] == "Drucker hat einen Fehler gemeldet: Abdeckung offen"
        )
        limited = ResourceAccess(
            "reader", False, frozenset(), {("printer", "main"): frozenset({"printer.view_audit"})}
        )
        projection = project_audit(event, limited, "de")
        assert projection is not None
        assert "reason" not in projection["fields"]
        assert "Abdeckung" not in json.dumps(projection)


def test_reason_migration_preserves_historical_text_and_rollback(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text

    config = Config("alembic.ini")
    url = f"sqlite:///{tmp_path / 'reasons.db'}"
    config.attributes["database_url"] = url
    command.upgrade(config, "56f102d9c843")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO printers (id, name, driver, config) VALUES ('history', 'History', 'mock', '{}')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO printer_state (id, printer_id, blocker) VALUES (99, 'history', 'Original reason')"
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT blocker, blocker_translation FROM printer_state WHERE id=99")
        ).one() == ("Original reason", None)
    command.downgrade(config, "56f102d9c843")
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT blocker FROM printer_state WHERE id=99")).scalar_one()
            == "Original reason"
        )
        assert "blocker_translation" not in {
            column["name"] for column in inspect(connection).get_columns("printer_state")
        }
    engine.dispose()
