import fcntl
from types import SimpleNamespace

import pytest

from app.printer.base import PrinterStatus, PrintInterrupted
from scripts import calibrate_tape


def no_hardware(*args, **kwargs):
    pytest.fail("This operation must not access the printer")


def test_estimate_only_never_accesses_hardware(monkeypatch, capsys):
    monkeypatch.setattr(calibrate_tape.BrotherPTP710BT, "get_status", no_hardware)
    monkeypatch.setattr(calibrate_tape.BrotherPTP710BT, "print_batch", no_hardware)
    assert calibrate_tape.main(["--serial", "test"]) == 0
    assert "Estimate only" in capsys.readouterr().out


def configure_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(
        calibrate_tape,
        "Settings",
        lambda: SimpleNamespace(database_url=f"sqlite:///{tmp_path / 'labels.db'}"),
    )
    return tmp_path / "labels.worker.lock"


def test_running_server_blocks_before_usb_access(monkeypatch, tmp_path, capsys):
    lock_path = configure_lock(monkeypatch, tmp_path)
    monkeypatch.setattr(calibrate_tape.BrotherPTP710BT, "get_status", no_hardware)
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert calibrate_tape.main(["--serial", "test", "--print"]) == 1
    assert "Stop the label server" in capsys.readouterr().out


@pytest.mark.parametrize(
    "status",
    [
        PrinterStatus(False, None, "Disconnected"),
        PrinterStatus(True, 12),
        PrinterStatus(True, 24, "Cover open"),
    ],
)
def test_unready_or_wrong_tape_never_prints(monkeypatch, tmp_path, status):
    configure_lock(monkeypatch, tmp_path)
    monkeypatch.setattr(calibrate_tape.BrotherPTP710BT, "get_status", lambda self: status)
    monkeypatch.setattr(calibrate_tape.BrotherPTP710BT, "print_batch", no_hardware)
    assert calibrate_tape.main(["--serial", "test", "--print"]) == 1


def test_uncertain_print_is_not_retried(monkeypatch, tmp_path, capsys):
    configure_lock(monkeypatch, tmp_path)
    monkeypatch.setattr(
        calibrate_tape.BrotherPTP710BT, "get_status", lambda self: PrinterStatus(True, 24)
    )
    attempts = []

    def interrupted(self, labels):
        attempts.append(labels)
        raise PrintInterrupted("USB disconnected")

    monkeypatch.setattr(calibrate_tape.BrotherPTP710BT, "print_batch", interrupted)
    assert calibrate_tape.main(["--serial", "test", "--copies", "3", "--print"]) == 1
    assert len(attempts) == 1
    assert "Output is uncertain" in capsys.readouterr().out
