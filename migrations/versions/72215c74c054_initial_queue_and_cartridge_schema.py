"""initial queue and cartridge schema

Revision ID: 72215c74c054
Revises:
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "72215c74c054"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tape_profiles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("width_mm", sa.Integer(), nullable=False),
        sa.Column("foreground", sa.String(), nullable=False),
        sa.Column("background", sa.String(), nullable=False),
        sa.Column("auto_print_threshold", sa.Integer(), nullable=False),
        sa.Column("waiting_notification_enabled", sa.Boolean(), nullable=False),
        sa.Column("waiting_notification_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("reminder_silenced", sa.Boolean(), nullable=False),
        sa.Column("reminder_snoozed_until", sa.Double(), nullable=True),
        sa.Column("reminder_last_at", sa.Double(), nullable=True),
        sa.Column("reminder_episode", sa.Integer(), nullable=False),
        sa.Column("reminder_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "cartridges",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("nominal_length_mm", sa.Double(), nullable=False),
        sa.Column("remaining_mm", sa.Double(), nullable=False),
        sa.Column("consumption_uncertain", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["tape_profiles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=True),
        sa.Column("episode", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("next_attempt_at", sa.Double(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("delivered_at", sa.Double(), nullable=True),
        sa.Column("cancelled", sa.Boolean(), nullable=False),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["tape_profiles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "print_jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("template_id", sa.String(), nullable=False),
        sa.Column("template_snapshot", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("width_mm", sa.Integer(), nullable=False),
        sa.Column("length_mm", sa.Double(), nullable=False),
        sa.Column("copies", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["tape_profiles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("print_jobs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_print_jobs_profile_id"), ["profile_id"], unique=False)

    op.create_table(
        "batches",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("cartridge_id", sa.String(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "QUEUED", "PRINTING", "PRINTED", "NEEDS_REVIEW", "CANCELLED", "FAILED", name="state"
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("finished_at", sa.Double(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("estimated_mm", sa.Double(), nullable=False),
        sa.Column("consumed_mm", sa.Double(), nullable=True),
        sa.Column("shortage_warning", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["cartridge_id"],
            ["cartridges.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "flush_requests",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("cartridge_id", sa.String(), nullable=False),
        sa.Column("copy_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Double(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["cartridge_id"],
            ["cartridges.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "label_copies",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "QUEUED", "PRINTING", "PRINTED", "NEEDS_REVIEW", "CANCELLED", "FAILED", name="state"
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["print_jobs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("label_copies", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_label_copies_job_id"), ["job_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_label_copies_state"), ["state"], unique=False)

    op.create_table(
        "printer_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("active_cartridge_id", sa.String(), nullable=True),
        sa.Column("blocker", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["active_cartridge_id"],
            ["cartridges.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "batch_items",
        sa.Column("batch_id", sa.String(), nullable=False),
        sa.Column("copy_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum(
                "QUEUED", "PRINTING", "PRINTED", "NEEDS_REVIEW", "CANCELLED", "FAILED", name="state"
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["batches.id"],
        ),
        sa.ForeignKeyConstraint(
            ["copy_id"],
            ["label_copies.id"],
        ),
        sa.PrimaryKeyConstraint("batch_id", "copy_id"),
    )


def downgrade() -> None:
    op.drop_table("batch_items")
    op.drop_table("printer_state")
    with op.batch_alter_table("label_copies", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_label_copies_state"))
        batch_op.drop_index(batch_op.f("ix_label_copies_job_id"))

    op.drop_table("label_copies")
    op.drop_table("flush_requests")
    op.drop_table("batches")
    with op.batch_alter_table("print_jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_print_jobs_profile_id"))

    op.drop_table("print_jobs")
    op.drop_table("notifications")
    op.drop_table("cartridges")
    op.drop_table("tape_profiles")
