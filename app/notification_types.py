"""Notification categories and default delivery preferences."""

from typing import Literal

NotificationKind = Literal[
    "general",
    "empty_tape",
    "printer_blocked",
    "batch_review",
    "tape_waiting",
    "approval_digest",
    "job_printed",
    "batch_printed",
]

PrinterNotificationKind = Literal[
    "empty_tape", "printer_blocked", "batch_review", "tape_waiting", "batch_printed"
]

PRINTER_NOTIFICATION_KINDS = frozenset(
    {"empty_tape", "printer_blocked", "batch_review", "tape_waiting", "batch_printed"}
)

PRINT_COMPLETION_KINDS = frozenset({"job_printed", "batch_printed"})

DEFAULT_NOTIFICATION_PRIORITIES: dict[NotificationKind, int] = {
    "general": 3,
    "empty_tape": 4,
    "printer_blocked": 4,
    "batch_review": 4,
    "tape_waiting": 3,
    "approval_digest": 3,
    "job_printed": 3,
    "batch_printed": 3,
}
