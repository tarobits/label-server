"""Notification categories and default delivery preferences."""

PRINTER_NOTIFICATION_KINDS = frozenset(
    {"empty_tape", "printer_blocked", "batch_review", "tape_waiting"}
)

DEFAULT_NOTIFICATION_PRIORITIES = {
    "general": 3,
    "empty_tape": 4,
    "printer_blocked": 4,
    "batch_review": 4,
    "tape_waiting": 3,
    "approval_digest": 3,
}
