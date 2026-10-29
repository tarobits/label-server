"""Detection overrides cross permissions, queue readiness, and the USB preflight."""

from collections import deque

import pytest
from conftest import install, job, profile
from sqlalchemy import select
from test_access_security import accounts as account_fixture
from test_brother import label

from app.models import PrinterState, Role
from app.printer.base import MediaSelection, PrintNotStarted
from app.printer.brother import BrotherPTP710BT

accounts = account_fixture


@pytest.mark.parametrize("pending", [False, True])
def test_manual_review_preserves_installed_cartridge_confirmation(client, pending):
    tape = profile(client, threshold=1)
    cartridge = install(client, tape["id"])
    queued = job(client, tape["id"])
    worker = client.app.state.fleet.workers["main"]
    worker.backend.fail_after = 0
    worker.tick()
    batch = client.get("/api/batches").json()[0]
    confirmation = {"cartridge_id": cartridge["id"], "fingerprint": "before-review"}
    with client.app.state.factory.begin() as session:
        state = session.scalar(select(PrinterState))
        state.media_confirmation = confirmation
        state.media_verified_fingerprint = "verified-before-review"
        state.cartridge_check_pending = pending
    response = client.post(
        f"/api/batches/{batch['id']}/review",
        json={"decisions": {queued["labels"][0]["id"]: "cancelled"}, "consumed_mm": 100},
    )
    assert response.status_code == 200, response.text
    assert client.get("/api/cartridges").json()[0]["remaining_mm"] == 7900
    with client.app.state.factory() as session:
        state = session.scalar(select(PrinterState))
        assert state.active_cartridge_id == cartridge["id"]
        assert state.media_confirmation == confirmation
        assert state.media_verified_fingerprint == "verified-before-review"
        assert state.cartridge_check_pending == pending
        assert state.cartridge_check_enabled


class DetectedTapeTransport:
    def __init__(self, *, width=24, media=0xFF):
        self.width, self.media = width, media
        self.tape_color, self.text_color = 4, 1
        self.errors = (0, 0)
        self.pending = deque()
        self.writes = []
        self.disconnected = False

    def packet(self, kind=0, phase=0, notification=0):
        value = bytearray(32)
        value[:4] = b"\x80\x20\x42\x30"
        value[4:6] = b"k0"
        value[8:12] = bytes((*self.errors, self.width, self.media))
        value[18:20] = bytes((kind, phase))
        value[22] = notification
        value[24:26] = bytes((self.tape_color, self.text_color))
        return bytes(value)

    def open(self):
        if self.disconnected:
            raise OSError("Disconnected")

    def close(self):
        pass

    def read(self, size, timeout_seconds):
        if self.pending:
            return self.pending.popleft()
        raise TimeoutError("No packet")

    def write(self, data):
        self.writes.append(data)
        if data == b"\x1biS":
            self.pending.append(self.packet())
        elif data.startswith(b"\x1biz"):
            self.pending.extend((self.packet(6, 1), self.packet(1), self.packet(6)))


def cartridge(client, tape):
    result = client.post(
        "/api/cartridges",
        json={
            "profile_id": tape["id"],
            "name": "Third-party white on red",
            "nominal_length_mm": 8000,
        },
    )
    assert result.status_code == 201, result.text
    return result.json()


def attach(client, **kwargs):
    transport = DetectedTapeTransport(**kwargs)
    worker = client.app.state.fleet.workers["main"]
    worker.backend = BrotherPTP710BT(transport)
    worker.latest_status = worker.backend.get_status()
    return worker, transport


def challenge(client, cart):
    response = client.put("/api/printer/active-tape", json={"cartridge_id": cart["id"]})
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "cartridge_mismatch"
    return detail


def confirm(client, cart, token):
    return client.put(
        "/api/printer/active-tape",
        json={
            "cartridge_id": cart["id"],
            "media_confirmation": token,
        },
    )


@pytest.mark.parametrize("detected_width", [24, 12, 255])
def test_confirmation_allows_queued_print_and_retains_actual_detection(client, detected_width):
    tape = profile(client, threshold=1)
    cart = cartridge(client, tape)
    worker, transport = attach(client, width=detected_width)
    detail = challenge(client, cart)
    assert "Incompatible tape" in detail["message"]
    assert "White on Red" in detail["message"]
    assert client.get("/api/status").json()["active_cartridge_id"] is None
    assert confirm(client, cart, detail["confirmation"]).status_code == 200
    status = client.get("/api/status").json()
    assert status["media_confirmed"]
    assert status["effective_width_mm"] == 24
    assert status["detected_width_mm"] == (None if detected_width == 255 else detected_width)
    assert status["printer_error"] is None
    assert status["diagnostics"]["Media type"] == "Incompatible tape · 0xff (255)"
    assert status["diagnostics"]["Raw status (32 bytes)"] == transport.packet().hex(" ")
    assert status["media_confirmation"] is None  # Internal acceptance/audit data stays internal.
    queued = job(client, tape["id"])
    worker.tick()
    assert client.get(f"/api/jobs/{queued['id']}").json()["status"] == "printed"
    page = next(data for data in transport.writes if data.startswith(b"\x1biz"))
    assert page[3:7] == bytes((0x80, 1, 24, 0))
    # The same confirmed installation does not prompt again.
    assert (
        client.put("/api/printer/active-tape", json={"cartridge_id": cart["id"]}).status_code == 200
    )


def test_stale_or_different_cartridge_confirmation_never_applies(client):
    tape = profile(client)
    first, second = cartridge(client, tape), cartridge(client, tape)
    worker, transport = attach(client)
    original = challenge(client, first)["confirmation"]
    assert confirm(client, second, original).status_code == 409
    transport.width = 12
    changed = confirm(client, first, original)
    assert changed.status_code == 409
    current = changed.json()["detail"]["confirmation"]
    assert current != original
    assert confirm(client, first, current).status_code == 200
    # A newly observed color change revokes the acceptance before any print starts.
    transport.tape_color = 5
    worker.tick()
    assert not client.get("/api/status").json()["media_confirmed"]
    with client.app.state.factory() as session:
        assert session.scalar(select(PrinterState)).media_confirmation is None
    assert not any(data.startswith(b"\x1biz") for data in transport.writes)


def test_swapping_or_editing_profile_requires_a_new_confirmation(client):
    tape = profile(client)
    cart = cartridge(client, tape)
    worker, _ = attach(client)
    assert confirm(client, cart, challenge(client, cart)["confirmation"]).status_code == 200
    assert client.put("/api/printer/active-tape", json={"cartridge_id": None}).status_code == 200
    challenge(client, cart)
    assert confirm(client, cart, challenge(client, cart)["confirmation"]).status_code == 200
    changed = client.put(
        f"/api/tape-profiles/{tape['id']}",
        json={
            "name": tape["name"],
            "width_mm": 24,
            "foreground": "#ffffff",
            "background": "#ff0000",
        },
    )
    assert changed.status_code == 200, changed.text
    worker.tick()
    assert not client.get("/api/status").json()["media_confirmed"]
    challenge(client, cart)


@pytest.mark.parametrize("errors", [(1, 0), (4, 0), (8, 0), (0, 1), (0, 0x10), (0, 0x20)])
def test_confirmation_cannot_bypass_hardware_errors(errors):
    transport = DetectedTapeTransport()
    backend = BrotherPTP710BT(transport)
    detected = backend.get_status()
    backend.configure_media(MediaSelection(24, detected.media.fingerprint))
    assert backend.get_status().media_confirmed
    transport.errors = errors
    status = backend.get_status()
    assert status.error and not status.media_confirmed and not status.media.confirmable
    with pytest.raises(PrintNotStarted, match="Printer error"):
        backend.print_batch([label()])
    assert not any(data.startswith(b"\x1biz") for data in transport.writes)


def test_preflight_rechecks_detection_and_disconnect_invalidates_confirmation():
    transport = DetectedTapeTransport()
    backend = BrotherPTP710BT(transport)
    status = backend.get_status()
    backend.configure_media(MediaSelection(24, status.media.fingerprint))
    transport.text_color = 8
    with pytest.raises(PrintNotStarted, match="confirm the installed cartridge"):
        backend.print_batch([label()])
    transport.text_color = 1
    assert not backend.get_status().media_confirmed
    status = backend.get_status()
    backend.configure_media(MediaSelection(24, status.media.fingerprint))
    assert backend.get_status().media_confirmed
    transport.disconnected = True
    assert not backend.get_status().connected
    transport.disconnected = False
    assert not backend.get_status().media_confirmed


def test_only_users_with_cartridge_swap_access_can_confirm(accounts):
    admin, alice, _ = accounts
    tape = profile(admin)
    cart = cartridge(admin, tape)
    attach(admin)
    token = challenge(admin, cart)["confirmation"]
    for level in ("request", "print", "moderator"):
        with admin.app.state.factory.begin() as session:
            session.get(Role, "alice-access").permissions = [
                {"kind": "destination", "destination_id": "main", "level": level},
            ]
        assert confirm(alice, cart, token).status_code == 403
    with admin.app.state.factory.begin() as session:
        session.get(Role, "alice-access").permissions = [
            {"kind": "destination", "destination_id": "main", "level": "full"},
        ]
    assert confirm(alice, cart, token).status_code == 200
    with admin.app.state.factory() as session:
        saved = session.scalar(select(PrinterState)).media_confirmation
        assert saved["confirmed_by"]["id"] == "alice"
        assert saved["confirmed_at"] > 0


def test_busy_and_pending_flush_protection_is_preserved(client):
    tape = profile(client)
    cart = cartridge(client, tape)
    worker, _ = attach(client)
    with worker.printer_lock:
        response = client.put("/api/printer/active-tape", json={"cartridge_id": cart["id"]})
    assert response.status_code == 409 and "busy" in response.json()["detail"]
    assert confirm(client, cart, challenge(client, cart)["confirmation"]).status_code == 200
    queued = job(client, tape["id"])
    assert client.post("/api/queue/print").status_code == 202
    other = cartridge(client, tape)
    response = client.put("/api/printer/active-tape", json={"cartridge_id": other["id"]})
    assert response.status_code == 409 and "pending flush" in response.json()["detail"]
    worker.tick()
    assert client.get(f"/api/jobs/{queued['id']}").json()["status"] == "printed"


def test_cover_open_blocks_threshold_print_until_same_cartridge_is_confirmed(client):
    tape = profile(client, threshold=10)
    cart = cartridge(client, tape)
    worker, transport = attach(client, media=1)
    assert (
        client.put("/api/printer/active-tape", json={"cartridge_id": cart["id"]}).status_code == 200
    )
    queued = job(client, tape["id"], copies=10)
    transport.errors = (0, 0x10)
    worker.tick()
    opened = client.get("/api/status").json()
    assert opened["cartridge_check_enabled"] and opened["cartridge_check_pending"]
    assert not opened["cartridge_check_ready"]
    # Confirming while the cover is open must not acknowledge the cartridge.
    blocked = client.put("/api/printer/active-tape", json={"cartridge_id": cart["id"]})
    assert blocked.status_code == 409 and isinstance(blocked.json()["detail"], str)
    transport.errors = (0, 0)
    worker.tick()
    closed = client.get("/api/status").json()
    assert closed["cartridge_check_pending"] and closed["cartridge_check_ready"]
    assert "confirm the installed cartridge" in closed["printer_error"]
    assert not any(data.startswith(b"\x1biz") for data in transport.writes)
    assert client.get(f"/api/jobs/{queued['id']}").json()["status"] == "queued"
    detail = challenge(client, cart)
    assert "still the correct cartridge" in detail["message"]
    assert confirm(client, cart, detail["confirmation"]).status_code == 200
    assert not client.get("/api/status").json()["cartridge_check_pending"]
    worker.tick()
    assert client.get(f"/api/jobs/{queued['id']}").json()["status"] == "printed"


def test_quick_cover_notifications_are_observed_and_pending_check_survives_restart(client):
    tape = profile(client, threshold=1)
    cart = cartridge(client, tape)
    worker, transport = attach(client, media=1)
    assert (
        client.put("/api/printer/active-tape", json={"cartridge_id": cart["id"]}).status_code == 200
    )
    # The cover opened and closed between polls. The drain must observe both packets.
    notices = transport.packet(5, notification=1) + transport.packet(5, notification=2)
    transport.pending.extend((notices[:9], notices[9:]))
    worker.tick()
    status = client.get("/api/status").json()
    assert status["cartridge_check_pending"]
    before_restart = challenge(client, cart)["confirmation"]
    queued = job(client, tape["id"])
    worker.backend = BrotherPTP710BT(transport)
    worker.tick()
    assert client.get("/api/status").json()["cartridge_check_pending"]
    assert client.get(f"/api/jobs/{queued['id']}").json()["status"] == "queued"
    assert confirm(client, cart, before_restart).status_code == 409
    assert confirm(client, cart, challenge(client, cart)["confirmation"]).status_code == 200
    worker.tick()
    assert client.get(f"/api/jobs/{queued['id']}").json()["status"] == "printed"


def test_opening_again_invalidates_an_unsubmitted_cover_confirmation(client):
    tape = profile(client)
    cart = cartridge(client, tape)
    worker, transport = attach(client, media=1)
    assert (
        client.put("/api/printer/active-tape", json={"cartridge_id": cart["id"]}).status_code == 200
    )
    transport.pending.append(transport.packet(5, notification=2))
    worker.tick()
    original = challenge(client, cart)["confirmation"]
    transport.pending.append(transport.packet(5, notification=2))
    assert confirm(client, cart, original).status_code == 409
    assert client.get("/api/status").json()["cartridge_check_pending"]


def test_disable_cover_check_releases_pending_work_and_keeps_same_third_party_acceptance(client):
    tape = profile(client, threshold=1)
    cart = cartridge(client, tape)
    worker, transport = attach(client)
    assert confirm(client, cart, challenge(client, cart)["confirmation"]).status_code == 200
    transport.errors = (0, 0x10)
    worker.tick()
    transport.errors = (0, 0)
    worker.tick()
    assert client.get("/api/status").json()["cartridge_check_pending"]
    disabled = client.put("/api/printers/main/cartridge-check", json={"enabled": False})
    assert disabled.status_code == 200, disabled.text
    state = client.get("/api/status").json()
    assert not state["cartridge_check_enabled"] and not state["cartridge_check_pending"]
    assert state["media_confirmed"] and state["printer_error"] is None
    queued = job(client, tape["id"])
    # Another opening with detection disabled still respects a physical cover fault.
    transport.errors = (0, 0x10)
    worker.tick()
    assert not any(data.startswith(b"\x1biz") for data in transport.writes)
    transport.errors = (0, 0)
    worker.tick()
    assert client.get(f"/api/jobs/{queued['id']}").json()["status"] == "printed"
    with client.app.state.factory() as session:
        assert not session.scalar(select(PrinterState)).cartridge_check_enabled


def test_cover_notifications_in_final_preflight_stop_before_transmission():
    transport = DetectedTapeTransport(media=1)
    backend = BrotherPTP710BT(transport)
    hardware = backend.get_status()
    backend.configure_media(
        MediaSelection(24, verified_fingerprint=hardware.media.verification_key)
    )
    transport.pending.append(transport.packet(5, notification=2))
    with pytest.raises(PrintNotStarted, match="confirm the installed cartridge"):
        backend.print_batch([label()])
    assert not any(data.startswith(b"\x1biz") for data in transport.writes)


def test_cover_check_setting_requires_direct_full_access(accounts):
    admin, alice, _ = accounts
    for level in ("request", "print", "moderator"):
        with admin.app.state.factory.begin() as session:
            session.get(Role, "alice-access").permissions = [
                {"kind": "destination", "destination_id": "main", "level": level},
            ]
        assert (
            alice.put("/api/printers/main/cartridge-check", json={"enabled": False}).status_code
            == 403
        )
    with admin.app.state.factory.begin() as session:
        session.get(Role, "alice-access").permissions = [
            {"kind": "destination", "destination_id": "main", "level": "full"},
        ]
    assert (
        alice.put("/api/printers/main/cartridge-check", json={"enabled": False}).status_code == 200
    )
